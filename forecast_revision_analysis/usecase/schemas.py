from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class PeriodType(str, Enum):
    Q1 = "1q"
    Q2 = "2q"
    Q3 = "3q"
    Q4 = "4q"


class ConsolidationType(str, Enum):
    CONSOLIDATED = "consolidated"
    NON_CONSOLIDATED = "non_consolidated"


class MetricName(str, Enum):
    SALES = "sales"
    BUSSINESS_INCOME = "bussiness_income"  # 既存のDBカラム値（typo）に合わせて踏襲
    ORDINARY_INCOME = "ordinary_income"
    NET_INCOME = "net_income"  # 親会社の所有者（株主）に帰属する当期純利益
    NET_INCOME_TOTAL = "net_income_total"  # IFRS「当期利益」（非支配持分を含む合計）。net_incomeとは別建て
    EBITDA = "ebitda"
    EPS = "eps"
    DIVIDEND_PER_SHARE = "dividend_per_share"


class PeriodExtraction(BaseModel):
    period_type: PeriodType
    fiscal_year: Optional[int] = None
    consolidation_type: Optional[ConsolidationType] = None
    metric_name: MetricName
    label_raw: str
    prev_value: Optional[float] = None
    prev_value_upper: Optional[float] = None
    curr_value: Optional[float] = None
    curr_value_upper: Optional[float] = None
    prev_year_actual: Optional[float] = None


class Stage1Extraction(BaseModel):
    """Stage1（抽出）のresponseSchema。is_modifiedは含まない（コード側で確定するため）。"""

    prev_forecast_date: Optional[str] = None
    value_unit: Optional[str] = None
    periods: List[PeriodExtraction] = []
    reason_raw: Optional[str] = None


class Stage2Inference(BaseModel):
    """Stage2（推論）のresponseSchema。"""

    direct_factors: List[str] = []
    structural_vulnerability: List[str] = []
    spillover_conditions: List[str] = []
