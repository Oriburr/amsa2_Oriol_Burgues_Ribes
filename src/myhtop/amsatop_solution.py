import os
from typing import List, Optional, Tuple

from amsatop import Htop, Process, TaskType
from amsatop.utils import (
    StatFile,
    get_stat_file_from_path,
    get_status_file_from_path,
)

# Flag del kernel que indica que la tasca és un kernel thread
PF_KTHREAD = 0x00200000

# SIGHUP és el senyal 1, per tant la seva màscara és 2^(1-1) = 1
SIGHUP = 1
SIGHUP_MASK = 1 << (SIGHUP - 1)


class Amsatop(Htop):
    def __init__(self):
        super().__init__()

    def get_processes(self) -> List[Process]:
        return [process for process, _ in self._collect_tasks(with_priority=False)]

    def get_priorities(self) -> List[Process]:
        return [process for process, _ in self._collect_tasks(with_priority=True)]

    def get_hup(self) -> List[Process]:
        return [
            process
            for process, path in self._collect_tasks(with_priority=True)
            if self._ignores_sighup(path)
        ]

    def _collect_tasks(self, with_priority: bool) -> List[Tuple[Process, str]]:
        """Retorna (Process, carpeta a /proc) per cada procés, thread i kthread."""
        tasks: List[Tuple[Process, str]] = []

        for pid in self._list_numeric_entries(self.proc_folder):
            pid_path = os.path.join(self.proc_folder, pid)
            stat = self._read_stat(pid_path)
            if stat is None:
                continue  # El procés ha acabat mentre el llegíem

            is_kthread = (stat.flags & PF_KTHREAD) != 0
            task_type = TaskType.KTHREAD if is_kthread else TaskType.PROCESS
            tasks.append(
                (self._build_process(stat, task_type, with_priority), pid_path)
            )

            if not is_kthread:
                tasks.extend(self._collect_threads(pid, pid_path, with_priority))

        return tasks

    def _collect_threads(
        self, pid: str, pid_path: str, with_priority: bool
    ) -> List[Tuple[Process, str]]:
        """Retorna els threads d'un procés (les entrades de task/ diferents del pid)."""
        threads: List[Tuple[Process, str]] = []
        task_folder = os.path.join(pid_path, "task")

        for tid in self._list_numeric_entries(task_folder):
            if tid == pid:
                continue  # Aquesta entrada és el propi procés
            tid_path = os.path.join(task_folder, tid)
            stat = self._read_stat(tid_path)
            if stat is None:
                continue  # El thread ha acabat
            threads.append(
                (self._build_process(stat, TaskType.THREAD, with_priority), tid_path)
            )

        return threads

    @staticmethod
    def _list_numeric_entries(folder: str) -> List[str]:
        try:
            return [entry for entry in os.listdir(folder) if entry.isdigit()]
        except OSError:
            return []

    @staticmethod
    def _read_stat(path: str) -> Optional[StatFile]:
        try:
            return get_stat_file_from_path(os.path.join(path, "stat"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _build_process(
        stat: StatFile, task_type: TaskType, with_priority: bool
    ) -> Process:
        return Process(
            pid=stat.pid,
            command=stat.command,
            type=task_type,
            priority=stat.priority if with_priority else None,
        )

    @staticmethod
    def _ignores_sighup(path: str) -> bool:
        try:
            status = get_status_file_from_path(os.path.join(path, "status"))
        except (OSError, ValueError):
            return False
        if status is None or not status.SigIgn:
            return False
        return (int(status.SigIgn, 16) & SIGHUP_MASK) != 0
