"""Audio processing helpers and beat/frequency detection."""
import logging
import numpy as np
import sounddevice as sd
from dataclasses import dataclass
from typing import Callable
from threading import Thread, Event

try:
    import aubio
    HAS_AUBIO = True
except ImportError:
    aubio = None
    HAS_AUBIO = False

logger = logging.getLogger(__name__)


@dataclass
class AudioProcessor:
    """Handles audio input, beat detection, and frequency analysis."""

    buffer_size: int = 2048
    sample_rate: int = 44100
    channels: int = 1
    min_volume: float = 0.005
    beat_threshold: float = 0.01
    
    def __post_init__(self):
        self._running = Event()
        self._stream = None
        self._tempo_detect = None
        self._pitch_detect = None
        
        if HAS_AUBIO:
            hop_size = self.buffer_size // 2
            self._tempo_detect = aubio.tempo("default", self.buffer_size, hop_size, self.sample_rate)
            self._pitch_detect = aubio.pitch("default", self.buffer_size, hop_size, self.sample_rate)
            self._pitch_detect.set_unit("Hz")
            self._pitch_detect.set_silence(-40)
            logger.info("Aubio beat detection enabled")
        else:
            logger.warning("Aubio not available, using fallback beat detection")

    def start(self, callback: Callable[[bool, float, float], None]) -> None:
        """Start processing audio and call `callback(is_beat, frequency, volume)`."""
        if self._running.is_set():
            logger.warning("Audio processor already running")
            return
        
        self._running.set()
        
        def audio_callback(indata, frames, time_info, status):
            try:
                if status:
                    logger.warning(f"Audio callback status: {status}")
                
                samples = indata[:, 0].astype(np.float32)
                
                # Calculate volume
                volume = float(np.sum(samples ** 2) / len(samples))
                
                # Volume gate
                if volume < self.min_volume:
                    return
                
                # Detect beat and pitch
                is_beat, pitch = self._detect_beat(samples)
                
                if is_beat and pitch > 0:
                    try:
                        callback(is_beat, pitch, volume)
                    except Exception as e:
                        logger.error(f"Error in audio callback handler: {e}")
            
            except Exception as e:
                logger.error(f"Error in audio processing: {e}")
        
        try:
            self._stream = sd.InputStream(
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.buffer_size // 2,
                dtype='float32',
                callback=audio_callback
            )
            self._stream.start()
            logger.info(f"Audio stream started (rate={self.sample_rate}, buffer={self.buffer_size})")
            
        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")
            self._running.clear()
            raise

    def stop(self) -> None:
        """Stop audio processing."""
        if not self._running.is_set():
            return
        
        self._running.clear()
        
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
                logger.info("Audio stream stopped")
            except Exception as e:
                logger.error(f"Error stopping audio stream: {e}")
            finally:
                self._stream = None

    def _detect_beat(self, samples: np.ndarray) -> tuple[bool, float]:
        """Detect beat and return (is_beat, frequency)."""
        if HAS_AUBIO and self._tempo_detect and self._pitch_detect:
            try:
                samples_aubio = samples.astype(aubio.float_type)
                is_beat = bool(self._tempo_detect(samples_aubio)[0])
                pitch = float(self._pitch_detect(samples_aubio)[0])
                return is_beat, pitch
            except Exception as e:
                logger.error(f"Aubio detection error: {e}")
                return False, 0.0
        else:
            # Fallback: energy-based beat detection and FFT pitch
            try:
                energy = np.sum(samples ** 2) / len(samples)
                is_beat = energy > self.beat_threshold
                
                # FFT-based pitch estimation
                fft = np.abs(np.fft.rfft(samples))
                freqs = np.fft.rfftfreq(len(samples), 1.0 / self.sample_rate)
                peak_idx = np.argmax(fft)
                pitch = float(freqs[peak_idx]) if fft.sum() > 0 and peak_idx > 0 else 0.0
                
                return is_beat, pitch
            except Exception as e:
                logger.error(f"Fallback detection error: {e}")
                return False, 0.0
    
    @property
    def is_running(self) -> bool:
        """Check if audio processing is active."""
        return self._running.is_set()
