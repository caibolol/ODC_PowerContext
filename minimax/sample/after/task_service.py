def list_tasks(tasks, status=None):
    if status is None:
        return list(tasks)

    wanted = status.strip().casefold()
    if wanted not in ('todo', 'done'):
        raise ValueError("status must be either 'todo' or 'done'")

    return [
        task
        for task in tasks
        if task.get('status', 'todo').casefold() == wanted
    ]
