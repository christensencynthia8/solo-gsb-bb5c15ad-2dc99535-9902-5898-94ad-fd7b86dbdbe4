"""批注迁移：把旧版修订稿上的批注按全局顺序对齐迁移到新版修订稿。

步骤：
1. 对旧稿与新稿做与校时相同的全局最少编辑代价对齐，得到新稿每个字符对应
   的旧稿下标（-1 表示新增字符）；
2. 旧稿字符仅当被对齐到**相同字符**（非替换）时才算“存活”，其在新稿中的
   位置由反向映射给出；
3. 对每条批注：
   - 区间内字符全部存活 → complete；部分存活 → partial；无存活 → orphan；
   - 存活字符在新稿中的最小覆盖区间 [最小位置, 最大位置 + 1) 即迁移区间，
     区间内部的新增/替换字符一并纳入（区间外侧的新增字符不纳入）；
   - 片段首末毫秒取自新稿逐字时间轴（首字符 start、末字符 end）；
   - orphan 的新区间、片段与时间均为 null。
"""
from __future__ import annotations

from .alignment import align_chars
from .errors import InvalidTimelineError
from .schemas import (
    AnnotationMigrateRequest,
    AnnotationMigration,
    RevisedCharTimeline,
)


def validate_annotations(req: AnnotationMigrateRequest) -> None:
    """校验批注：区间非空、不越界、ID 全局唯一。

    前置条件：请求已通过与 /align 相同的输入校验。
    """
    old_len = len(req.old_revised_text)
    seen: set[str] = set()
    for idx, ann in enumerate(req.annotations):
        if ann.start < 0 or ann.end < 0:
            raise InvalidTimelineError(
                f"第 {idx} 条批注（annotation_id={ann.annotation_id!r}）"
                f"的区间下标不能为负数：start={ann.start}, end={ann.end}")
        if ann.start >= old_len or ann.end > old_len:
            raise InvalidTimelineError(
                f"第 {idx} 条批注（annotation_id={ann.annotation_id!r}）"
                f"的字符区间 [{ann.start}, {ann.end}) 越界："
                f"旧修订文本长度为 {old_len}")
        if ann.end <= ann.start:
            raise InvalidTimelineError(
                f"第 {idx} 条批注（annotation_id={ann.annotation_id!r}）"
                f"的字符区间必须是非空半开区间 [start, end)："
                f"start={ann.start}, end={ann.end}")
        if ann.annotation_id in seen:
            raise InvalidTimelineError(
                f"批注 ID 必须唯一：{ann.annotation_id!r} 重复出现")
        seen.add(ann.annotation_id)


def _survivor_positions(
        old_text: str, new_text: str) -> list[int | None]:
    """返回旧稿每个字符存活后在新稿中的位置；未存活（删除/被替换）为 None。"""
    new_to_old = align_chars(old_text, new_text)
    positions: list[int | None] = [None] * len(old_text)
    for new_idx, old_idx in enumerate(new_to_old):
        # 仅相同字符的匹配算存活；替换纠错（字符不同）不算同一字符。
        if old_idx >= 0 and old_text[old_idx] == new_text[new_idx]:
            positions[old_idx] = new_idx
    return positions


def migrate_annotations(
        req: AnnotationMigrateRequest,
        chars: list[RevisedCharTimeline]) -> list[AnnotationMigration]:
    """按旧→新全局对齐迁移每条批注，顺序与请求一致。"""
    positions = _survivor_positions(req.old_revised_text, req.revised_text)
    new_text = req.revised_text

    results: list[AnnotationMigration] = []
    for ann in req.annotations:
        moved = [p for p in positions[ann.start:ann.end] if p is not None]

        if not moved:
            results.append(AnnotationMigration(
                annotation_id=ann.annotation_id,
                status="orphan",
                original_start=ann.start,
                original_end=ann.end,
                start_index=None,
                end_index=None,
                text=None,
                start=None,
                end=None,
            ))
            continue

        # 对齐保持顺序，moved 必然非递减；最小覆盖区间包含其内部全部新字符
        # （新增字符、替换到旧稿被删字符上的字符均一并纳入）。
        start_index = min(moved)
        end_index = max(moved) + 1
        total = ann.end - ann.start
        status = "complete" if len(moved) == total else "partial"

        results.append(AnnotationMigration(
            annotation_id=ann.annotation_id,
            status=status,
            original_start=ann.start,
            original_end=ann.end,
            start_index=start_index,
            end_index=end_index,
            text=new_text[start_index:end_index],
            start=chars[start_index].start,
            end=chars[end_index - 1].end,
        ))
    return results
