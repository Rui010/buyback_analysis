from pathlib import Path


def load_prompt_template(filename: str, **kwargs) -> str:
    """
    指定されたテンプレートファイルを読み込み、変数を埋め込んで返す
    """
    base_dir = Path(__file__).resolve().parents[1]  # プロジェクトルート
    prompt_path = base_dir / "prompts" / filename

    with open(prompt_path, encoding="utf-8") as f:
        template = f.read()
    return template.format(**kwargs)
