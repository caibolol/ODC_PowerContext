# 任务列表规格

## TASK-1 原有行为
不传筛选条件时返回全部任务，保持输入顺序，返回列表副本，不修改输入。

## TASK-2 状态筛选
`list_tasks(tasks, status=None)`：status 非 None 时，先 strip().casefold()，
只允许 todo、done，否则抛出 ValueError。记录中的 status 使用 casefold() 比较，
缺失 status 的任务视为 todo。筛选后保持顺序，不修改输入。
输入任务为字典，存在的 status 字段为字符串；筛选参数为字符串或 None。
