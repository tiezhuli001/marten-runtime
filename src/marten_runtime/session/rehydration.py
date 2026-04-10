from marten_runtime.session.compaction import ContextSnapshot


def rehydrate_context(snapshot: ContextSnapshot) -> dict:
    return {
        "active_goal": snapshot.active_goal,
        "user_constraints": snapshot.user_constraints,
        "recent_files": snapshot.recent_files,
        "open_todos": snapshot.open_todos,
        "recent_decisions": snapshot.recent_decisions,
        "recent_results": snapshot.recent_results,
        "pending_risks": snapshot.pending_risks,
        "continuation_hint": snapshot.continuation_hint,
        "source_message_range": snapshot.source_message_range,
    }
