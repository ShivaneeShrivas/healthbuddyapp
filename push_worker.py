"""Background push worker — run as a SECOND process alongside gunicorn, for
LOCAL DEV or any host where a real always-on worker process is available/paid
for. If you're on a free host without a background-worker tier, use the
/api/push/run-tick HTTP endpoint + a free external cron pinger instead (see
NOTIFICATIONS_SETUP.md) - same underlying logic, no paid worker needed.

Sends real phone notifications on a fixed 4-times-a-day schedule: morning
(~8am), afternoon (~1pm), evening (~6pm), night (~9pm), plus due "Remind in
1h" snoozes.

Run it:
    python push_worker.py
"""
import time

from healthbuddy import create_app
from healthbuddy.services import scheduler

CHECK_EVERY_SECONDS = 60  # cheap to check often; compose_slot()/due_snoozes() do the real gating


def main():
    app = create_app()
    print("[push_worker] starting - 4 fixed daily slots: "
          "morning ~8am, afternoon ~1pm, evening ~6pm, night ~9pm "
          "(quiet hours enforced per-user inside notify.py)")
    while True:
        try:
            with app.app_context():
                result = scheduler.run_tick_once()
                for line in result["detail"]:
                    print(f"[push_worker] sent {line}")
        except Exception as e:  # keep the loop alive across transient errors
            print(f"[push_worker] error: {e}")
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
