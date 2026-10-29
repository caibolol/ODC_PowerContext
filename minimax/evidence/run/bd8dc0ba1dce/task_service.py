def list_tasks(tasks, status=None):
    if status is None:
        return list(tasks)

    normalized_status = status.strip().casefold()
    if normalized_status not in ("todo", "done"):
        raise ValueError("status must be 'todo' or 'done'")

    return [
        task
        for task in tasks
        if task.get("status", "todo").casefold() == normalized_status
    ]
