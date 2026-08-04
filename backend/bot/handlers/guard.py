"""
Permission guard — single source of truth.
Every handler calls `is_owner` before executing any logic.

Also tracks runtime timestamps:
  - last_command: when the owner's last command was processed
  - last_update: when the last Telegram update was received
"""
from backend.health import set_last_command
from backend.diagnostics_system import trace_step


def is_owner(event, owner_id: int) -> bool:
    result = bool(event.sender_id and event.sender_id == owner_id)
    if result:
        try:
            set_last_command()
        except Exception:
            pass
        trace_step("guard", "guard", "permission_check",
                    function="is_owner",
                    status="success",
                    sender_id=str(event.sender_id),
                    chat_id=str(event.chat_id))
    else:
        trace_step("guard", "guard", "permission_check",
                    function="is_owner",
                    status="denied",
                    sender_id=str(event.sender_id) if event.sender_id else "none")
    return result
