"""
core/sim_clock.py — Simulation Clock tách biệt khỏi wall clock
================================================================
Cho phép:
  - Fast-forward: speed=10 → 1 giây thật = 10 giây mô phỏng
  - Slow-motion:  speed=0.5 → 1 giây thật = 0.5 giây mô phỏng
  - Jump:         nhảy tới giờ/phút bất kỳ (test cao điểm lúc nửa đêm)
  - Pause/Resume: dừng/tiếp tục mô phỏng

Tham chiếu:
  - Tách wall clock khỏi simulation time là practice chuẩn
    trong mọi simulation engine (SUMO, Vissim, AnyLogic, etc.)
"""
from __future__ import annotations

import logging

logger = logging.getLogger("sim_clock")


class SimulationClock:
    """
    Đồng hồ mô phỏng độc lập — quản lý sim-time tách biệt real-time.

    Attributes
    ----------
    _total_seconds : float
        Tổng giây mô phỏng đã trôi qua kể từ thời điểm bắt đầu.
    _speed : float
        Hệ số tốc độ. 1.0 = realtime, 10.0 = 10x, 0.5 = slow-motion.
    _paused : bool
        True nếu đồng hồ đang tạm dừng.
    _start_seconds : float
        Thời điểm bắt đầu tính bằng giây từ 00:00.

    Usage
    -----
    >>> clock = SimulationClock(start_hour=7, start_minute=30, speed=1.0)
    >>> clock.tick()          # Tiến 1 sim-second
    >>> clock.hour            # 7
    >>> clock.set_speed(10)   # Fast-forward 10x
    >>> clock.jump_to(17, 0)  # Nhảy tới 17:00
    """

    def __init__(
        self,
        start_hour: int = 7,
        start_minute: int = 30,
        speed: float = 1.0,
    ) -> None:
        self._start_seconds: float = start_hour * 3600.0 + start_minute * 60.0
        self._total_seconds: float = 0.0
        self._speed: float = max(0.1, speed)
        self._paused: bool = False

        logger.info(
            f"🕐 SimClock khởi tạo: {start_hour:02d}:{start_minute:02d}, "
            f"speed={self._speed}x"
        )

    # ── Properties ────────────────────────────────────────────────

    @property
    def current_seconds(self) -> float:
        """Tổng giây trong ngày hiện tại (0-86399)."""
        return (self._start_seconds + self._total_seconds) % 86400.0

    @property
    def hour(self) -> int:
        """Giờ hiện tại (0-23)."""
        return int(self.current_seconds // 3600) % 24

    @property
    def minute(self) -> int:
        """Phút hiện tại (0-59)."""
        return int((self.current_seconds % 3600) // 60)

    @property
    def second(self) -> int:
        """Giây hiện tại (0-59)."""
        return int(self.current_seconds % 60)

    @property
    def time_str(self) -> str:
        """Chuỗi thời gian HH:MM:SS."""
        return f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}"

    @property
    def speed(self) -> float:
        """Hệ số tốc độ hiện tại."""
        return self._speed

    @property
    def total_sim_seconds(self) -> float:
        """Tổng giây mô phỏng đã trôi qua."""
        return self._total_seconds

    @property
    def paused(self) -> bool:
        """True nếu đồng hồ đang tạm dừng."""
        return self._paused

    @property
    def day(self) -> int:
        """Ngày mô phỏng (bắt đầu từ 1)."""
        total = self._start_seconds + self._total_seconds
        return int(total // 86400) + 1

    # ── Core Methods ──────────────────────────────────────────────

    def tick(self, dt_real: float = 1.0) -> float:
        """
        Tiến đồng hồ mô phỏng 1 bước.

        Parameters
        ----------
        dt_real : float
            Khoảng thời gian thật (giây) giữa các tick.
            Mặc định = 1.0s.

        Returns
        -------
        float
            Số giây mô phỏng thực sự đã trôi qua trong tick này.
            = 0 nếu đang paused, = dt_real * speed nếu đang chạy.
        """
        if self._paused:
            return 0.0

        dt_sim = dt_real * self._speed
        self._total_seconds += dt_sim
        return dt_sim

    def set_speed(self, multiplier: float) -> None:
        """
        Đặt hệ số tốc độ mô phỏng.

        Parameters
        ----------
        multiplier : float
            0.1 = slow-motion (10x chậm)
            1.0 = realtime
            10.0 = fast-forward 10x
            60.0 = 1 phút thật = 1 giờ mô phỏng
        """
        old_speed = self._speed
        self._speed = max(0.1, min(3600.0, multiplier))
        logger.info(
            f"🕐 SimClock speed: {old_speed}x → {self._speed}x "
            f"(tại {self.time_str})"
        )

    def jump_to(self, hour: int, minute: int = 0) -> None:
        """
        Nhảy đến giờ:phút bất kỳ trong ngày.

        Nếu giờ đích < giờ hiện tại → nhảy sang ngày tiếp theo.

        Parameters
        ----------
        hour   : int — giờ đích (0-23)
        minute : int — phút đích (0-59)
        """
        target_seconds_in_day = hour * 3600.0 + minute * 60.0
        current = self.current_seconds

        if target_seconds_in_day <= current:
            # Nhảy sang ngày hôm sau
            jump = (86400.0 - current) + target_seconds_in_day
        else:
            jump = target_seconds_in_day - current

        self._total_seconds += jump
        logger.info(
            f"⏭️  SimClock JUMP → {hour:02d}:{minute:02d} "
            f"(nhảy {jump:.0f}s, day {self.day})"
        )

    def pause(self) -> None:
        """Tạm dừng đồng hồ mô phỏng."""
        self._paused = True
        logger.info(f"⏸️  SimClock PAUSED tại {self.time_str}")

    def resume(self) -> None:
        """Tiếp tục đồng hồ mô phỏng."""
        self._paused = False
        logger.info(f"▶️  SimClock RESUMED tại {self.time_str}")

    def to_dict(self) -> dict:
        """Serialize trạng thái clock → JSON-friendly dict."""
        return {
            "hour": self.hour,
            "minute": self.minute,
            "second": self.second,
            "time_str": self.time_str,
            "speed": self._speed,
            "paused": self._paused,
            "day": self.day,
            "total_sim_seconds": round(self._total_seconds, 1),
        }
