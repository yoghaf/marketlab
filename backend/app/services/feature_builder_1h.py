from sqlalchemy.orm import Session

from app.models.market import FuturesKline1h, MarketFeature1h, SpotKline1h
from app.services.feature_builder import FeatureBuildResult, TimeframeFeatureBuilderService


class FeatureBuilder1hService(TimeframeFeatureBuilderService):
    def __init__(self, db: Session) -> None:
        super().__init__(
            db=db,
            timeframe="1h",
            futures_model=FuturesKline1h,
            spot_model=SpotKline1h,
            feature_model=MarketFeature1h,
        )
