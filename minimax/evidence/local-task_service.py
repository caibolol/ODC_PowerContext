def list_tasks(tasks, status=None):
    # 无筛选时保持原有行为，返回独立列表。
    if status is None:
        return list(tasks)
    normalized = status.strip().casefold()
    if normalized not in {'todo', 'done'}:
        raise ValueError('status must be todo or done')
    # 缺省状态为 todo，不修改调用者的任务记录。
    return [task for task in tasks
            if task.get('status', 'todo').casefold() == normalized]
