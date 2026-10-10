"""数据模型（Pydantic v2）。仅做类型与范围约束，持久化由 storage.db 负责。"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional

# 六个口味维度，每项 1-5 分
TASTE_DIMENSIONS = ["酸", "甜", "辣", "麻", "清淡", "咸香"]

DIM_MIN = 1.0
DIM_MAX = 5.0


class TasteProfile(BaseModel):
    dimensions: dict[str, float] = Field(default_factory=lambda: {d: 3.0 for d in TASTE_DIMENSIONS})
    allergens: list[str] = Field(default_factory=list)          # 过敏原
    avoid_foods: list[str] = Field(default_factory=list)        # 忌口食材
    religious_rules: list[str] = Field(default_factory=list)    # 宗教饮食规则
    disliked_dishes: list[str] = Field(default_factory=list)    # 标记不想再吃的菜
    updated_at: Optional[str] = None                            # 更新时间戳（ISO8601）

    def clamp_dimensions(self) -> None:
        for k in self.dimensions:
            self.dimensions[k] = max(DIM_MIN, min(DIM_MAX, round(self.dimensions[k], 2)))


class MealRecord(BaseModel):
    dish_name: str
    rating: int = Field(ge=1, le=5)     # 评分 1-5
    scene: str                          # 场景：工作日午餐/周末聚餐/外卖/在家做饭/其他
    timestamp: Optional[str] = None     # 时间戳（ISO8601），缺省由存储层填当前时间


class PreferenceLogEntry(BaseModel):
    timestamp: str
    rule: str                           # meal_rating / streak_bonus / manual / dislike
    dimension: Optional[str] = None
    delta: Optional[float] = None
    reason: Optional[str] = None
