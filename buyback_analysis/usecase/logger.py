import json
import logging
import os


class Logger:
    def __init__(
        self, log_dir="logs", log_file="app.log", failed_data_file="failed_data.log"
    ):
        """
        ロガーを初期化する

        Args:
            log_dir (str): ログファイルを保存するディレクトリ
            log_file (str): ログファイル名
        """
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)
        failed_data_path = os.path.join(log_dir, failed_data_file)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_path, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("buyback_analysis")

    def info(self, message):
        """情報ログを出力"""
        self.logger.info(message)

    def error(self, message):
        """エラーログを出力"""
        self.logger.error(message)

    def log_failed_data(self, data, error_message):
        """
        失敗したデータをログファイルに記録する

        Args:
            data (dict): 保存に失敗したデータ
            error_message (str): エラーメッセージ
        """
        with open(self.failed_data_path, "a", encoding="utf-8") as f:
            log_entry = {
                "data": data,
                "error": error_message,
            }
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        self.logger.error(f"データの保存に失敗しました: {error_message}")
