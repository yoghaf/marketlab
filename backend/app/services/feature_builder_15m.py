from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, MarketFeature15m, SpotKline15m
from app.services.feature_builder import FeatureBuildResult, TimeframeFeatureBuilderService


class FeatureBuilder15mService(TimeframeFeatureBuilderService):
    def __init__(self, db: Session) -> None:
        super().__init__(
            db=db,
            timeframe="15m",
            futures_model=FuturesKline15m,
            spot_model=SpotKline15m,
            feature_model=MarketFeature15m,
        )
