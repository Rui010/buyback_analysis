from sqlalchemy import Column, Integer, String

from tdnet_provenance.models.base import ProvenanceBase


class TdnetSourceDocument(ProvenanceBase):
    """運用原典台帳。URLごとに1行で、登録後は更新・削除しない。"""

    __tablename__ = "tdnet_source_documents"

    url = Column(String, primary_key=True)
    source_document_id = Column(String, nullable=False, unique=True)  # uuid5(TDNET_NAMESPACE, "tdnet:<文書ID>")
    external_document_id = Column(String, nullable=False)  # URL末尾から.pdfを除いた文書ID
    disclosure_date = Column(String, nullable=False)  # TDnet公表日 YYYY-MM-DD
    published_at = Column(String)  # TDnet date + time（+09:00）。timeが不明ならNULL
    storage_uri = Column(String, nullable=False)  # tdnet-pdf://<公表日YYYYMMDD>/<文書ID>.pdf
    source_hash = Column(String(64), nullable=False)  # 登録時のPDF全バイトSHA-256（小文字64桁）
    file_size = Column(Integer, nullable=False)
    fetched_at = Column(String)  # 新規ダウンロード時のみ。既存ファイル登録時はNULL
    observed_at = Column(String, nullable=False)  # 台帳登録時刻。source_hashはこの時刻以降の基準値
