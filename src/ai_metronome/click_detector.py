"""PDM Microphone Click / Transient Onset Detection Algorithm for XIAO nRF52840 Sense.

Designed for 16 kHz, 16-bit unsigned ('H') PDM DMA buffers on Nordic nRF52840:
1. Single-pass first-difference high-pass filter H(z) = 1 - z^-1 removes DC bias
   and attenuates low-frequency hum while amplifying sharp 1-6 kHz click transients.
2. Dual-condition adaptive threshold (Peak & Mean SNR + Crest + Attack Slope)
   with asymmetric EMA noise-floor tracking.
3. Refractory debounce window prevents double-triggering on room reflections.
4. Inter-Onset Interval (IOI) tracker computes live BPM.
"""


class ClickFrameResult:
    """Result of processing a single audio buffer frame."""

    def __init__(
        self,
        is_click: bool,
        hp_mean: float,
        hp_peak: int,
        noise_floor: float,
        click_count: int,
        bpm: float | None,
    ) -> None:
        self.is_click = is_click
        self.hp_mean = hp_mean
        self.hp_peak = hp_peak
        self.noise_floor = noise_floor
        self.click_count = click_count
        self.bpm = bpm


def extract_highpass_features(sample_buffer) -> tuple[float, int]:
    """Compute single-pass first-difference high-pass mean and peak across a 16-bit buffer.

    Returns:
        (hp_mean, hp_peak) where:
        - hp_mean: average |s[i] - s[i-1]| across the window
        - hp_peak: maximum |s[i] - s[i-1]| in the window
    """
    count = len(sample_buffer)
    if count < 2:
        return 0.0, 0

    hp_sum = 0
    hp_peak = 0
    prev = sample_buffer[0]

    for i in range(1, count):
        curr = sample_buffer[i]
        diff = curr - prev
        if diff < 0:
            diff = -diff
        hp_sum += diff
        if diff > hp_peak:
            hp_peak = diff
        prev = curr

    hp_mean = hp_sum / (count - 1)
    return hp_mean, hp_peak


class PDMClickDetector:
    """Adaptive high-pass transient click detector and tempo estimator."""

    def __init__(
        self,
        peak_snr_mult: float = 6.0,
        mean_snr_mult: float = 1.6,
        min_peak_threshold: int = 800,
        attack_slope_ratio: float = 1.8,
        refractory_sec: float = 0.12,
        ema_alpha: float = 0.04,
    ) -> None:
        self.peak_snr_mult = peak_snr_mult
        self.mean_snr_mult = mean_snr_mult
        self.min_peak_threshold = min_peak_threshold
        self.attack_slope_ratio = attack_slope_ratio
        self.refractory_sec = refractory_sec
        self.ema_alpha = ema_alpha

        self.noise_floor_mean: float = 40.0
        self.noise_floor_peak: float = 120.0
        self.prev_hp_peak: int = 0
        self.last_click_time: float = -10.0
        self.click_count: int = 0
        self.recent_intervals: list[float] = []
        self.bpm: float | None = None
        self.is_calibrated: bool = False

        self._cal_means: list[float] = []
        self._cal_peaks: list[int] = []

    def calibrate_step(self, sample_buffer) -> tuple[float, int]:
        """Record one ambient noise buffer during startup calibration."""
        hp_mean, hp_peak = extract_highpass_features(sample_buffer)
        self._cal_means.append(hp_mean)
        self._cal_peaks.append(hp_peak)
        return hp_mean, hp_peak

    def finalize_calibration(self) -> tuple[float, float]:
        """Compute baseline ambient noise floor from collected calibration frames."""
        if self._cal_means:
            avg_mean = sum(self._cal_means) / len(self._cal_means)
            avg_peak = sum(self._cal_peaks) / len(self._cal_peaks)
            self.noise_floor_mean = max(15.0, avg_mean)
            self.noise_floor_peak = max(60.0, avg_peak)
            self.prev_hp_peak = int(self.noise_floor_peak)
        self.is_calibrated = True
        return self.noise_floor_mean, self.noise_floor_peak

    def process_frame(self, sample_buffer, now: float) -> ClickFrameResult:
        """Analyze an audio frame and determine if a click onset occurred."""
        hp_mean, hp_peak = extract_highpass_features(sample_buffer)

        # Dynamic thresholds scaled from tracked ambient noise floor
        peak_thresh = max(
            float(self.min_peak_threshold),
            self.noise_floor_peak * self.peak_snr_mult,
        )
        mean_thresh = max(25.0, self.noise_floor_mean * self.mean_snr_mult)

        elapsed = now - self.last_click_time
        in_refractory = elapsed < self.refractory_sec

        # Crest factor ensures percussive impulse rather than continuous loud broadband noise
        crest_ratio = hp_peak / (hp_mean + 1.0)
        is_sharp_attack = hp_peak >= (self.prev_hp_peak * self.attack_slope_ratio)

        is_click = (
            (not in_refractory)
            and (hp_peak >= peak_thresh)
            and (hp_mean >= mean_thresh)
            and (crest_ratio >= 2.2)
            and is_sharp_attack
        )

        if is_click:
            self.click_count += 1
            if self.last_click_time > 0.0 and 0.18 <= elapsed <= 2.5:
                self.recent_intervals.append(elapsed)
                if len(self.recent_intervals) > 4:
                    self.recent_intervals.pop(0)
                avg_ioi = sum(self.recent_intervals) / len(self.recent_intervals)
                self.bpm = 60.0 / avg_ioi
            self.last_click_time = now
        elif not in_refractory and hp_peak < peak_thresh * 0.7:
            # Slowly adapt noise floor only during non-transient background frames
            alpha = self.ema_alpha
            self.noise_floor_mean = (1.0 - alpha) * self.noise_floor_mean + alpha * hp_mean
            self.noise_floor_peak = (1.0 - alpha) * self.noise_floor_peak + alpha * hp_peak
            self.noise_floor_mean = max(15.0, self.noise_floor_mean)
            self.noise_floor_peak = max(60.0, self.noise_floor_peak)

        self.prev_hp_peak = hp_peak

        return ClickFrameResult(
            is_click=is_click,
            hp_mean=hp_mean,
            hp_peak=hp_peak,
            noise_floor=self.noise_floor_peak,
            click_count=self.click_count,
            bpm=self.bpm,
        )
