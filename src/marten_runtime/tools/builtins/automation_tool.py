from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.automation.store import AutomationStore
from marten_runtime.tools.builtins.delete_automation_tool import run_delete_automation_tool
from marten_runtime.tools.builtins.get_automation_detail_tool import run_get_automation_detail_tool
from marten_runtime.tools.builtins.list_automations_tool import run_list_automations_tool
from marten_runtime.tools.builtins.pause_automation_tool import run_pause_automation_tool
from marten_runtime.tools.builtins.register_automation_tool import run_register_automation_tool
from marten_runtime.tools.builtins.resume_automation_tool import run_resume_automation_tool
from marten_runtime.tools.builtins.update_automation_tool import run_update_automation_tool


def run_automation_tool(
    payload: dict,
    store: AutomationStore,
    adapter: DomainDataAdapter,
) -> dict:
    action = str(payload.get("action", "")).strip().lower()
    request = {key: value for key, value in payload.items() if key != "action"}
    if action == "register":
        result = run_register_automation_tool(request, store, adapter)
    elif action == "list":
        result = run_list_automations_tool(request, adapter)
    elif action == "detail":
        result = run_get_automation_detail_tool(request, adapter)
    elif action == "update":
        result = run_update_automation_tool(request, adapter)
    elif action == "delete":
        result = run_delete_automation_tool(request, adapter)
    elif action == "pause":
        result = run_pause_automation_tool(request, adapter)
    elif action == "resume":
        result = run_resume_automation_tool(request, adapter)
    else:
        raise ValueError("unsupported automation action")
    return {"action": action, **result}
