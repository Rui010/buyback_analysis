import json
import logging
import os
from logging.handlers import TimedRotatingFileHandler


class Logger:
    def __init__(
        self, log_dir=None, log_file=None, failed_data_file="failed_data.log"
    ):
        log_dir = log_dir or os.getenv("LOG_DIR", "logs")
        log_file = log_file or os.getenv("LOG_FILE", "app.log")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, log_file)
        self.failed_data_path = os.path.join(log_dir, failed_data_file)

        backup_count = int(os.getenv("LOG_BACKUP_COUNT", "30"))
        rotating_handler = TimedRotatingFileHandler(
            log_path,
            when="midnight",
            backupCount=backup_count,
            encoding="utf-8",
        )
        rotating_handler.suffix = "%Y-%m-%d"

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                rotating_handler,
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("buyback_analysis")

    def info(self, message):
        self.logger.info(message)

    def error(self, message):
        self.logger.error(message)

    def log_failed_data(self, data, error_message):
        with open(self.failed_data_path, "a", encoding="utf-8") as f:
            log_entry = {
                "data": data,
                "error": error_message,
            }
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        self.logger.error(f"データの保存に失敗しました: {error_message}")
