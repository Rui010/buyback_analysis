import logging
import os


class Logger:
    def __init__(self, log_dir="logs", log_file="app.log"):
        """
        ロガーを初期化する

        Args:
            log_dir (str): ログファイルを保存するディレクトリ
            log_file (str): ログファイル名
        """
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_path, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("GetStakeholderData")

    def info(self, message):
        """情報ログを出力"""
        self.logger.info(message)

    def error(self, message):
        """エラーログを出力"""
        self.logger.error(message)
