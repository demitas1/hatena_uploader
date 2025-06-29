#!/usr/bin/env python3
"""
Astro ブログ記事をはてなブログ形式に変換するツール
"""

import re
import sys
import argparse
import yaml
from typing import List, Dict, Any
from pathlib import Path


class AstroToHatenaConverter:
    """Astro形式のマークダウンをはてなブログ形式に変換するクラス"""

    def __init__(self):
        self.warnings = []

    def convert_frontmatter(self, frontmatter: Dict[str, Any]) -> str:
        """フロントマターを変換"""
        if 'tags' in frontmatter and isinstance(frontmatter['tags'], list):
            # タグをカンマ区切りの文字列に変換
            frontmatter['tags'] = ', '.join(frontmatter['tags'])

        # YAMLとして出力
        return yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)

    def convert_strikethrough(self, content: str) -> str:
        """打ち消し線を~~からHTMLタグに変換"""
        return re.sub(r'~~(.+?)~~', r'<s>\1</s>', content)

    def convert_lists(self, content: str) -> str:
        """リストをHTML形式に変換"""
        lines = content.split('\n')
        result = []
        in_ul = False
        in_ol = False
        indent_level = 0

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)

            # 順序なしリストの処理
            if re.match(r'^- ', stripped):
                if not in_ul or current_indent > indent_level:
                    if in_ol:
                        result.append('</ol>')
                        in_ol = False
                    if current_indent > indent_level:
                        result.append('    ' * (current_indent // 2) + '<ul>')
                    elif not in_ul:
                        result.append('<ul>')
                    in_ul = True
                    indent_level = current_indent
                elif current_indent < indent_level:
                    result.append('    ' * (current_indent // 2) + '</ul>')
                    indent_level = current_indent

                item_text = stripped[2:]  # "- "を除去
                result.append('    ' * (current_indent // 2 + 1) + f'<li> {item_text} </li>')

            # 順序ありリストの処理
            elif re.match(r'^\d+\. ', stripped):
                if not in_ol or current_indent > indent_level:
                    if in_ul:
                        result.append('</ul>')
                        in_ul = False
                    if current_indent > indent_level:
                        result.append('    ' * (current_indent // 2) + '<ol>')
                    elif not in_ol:
                        result.append('<ol>')
                    in_ol = True
                    indent_level = current_indent
                elif current_indent < indent_level:
                    result.append('    ' * (current_indent // 2) + '</ol>')
                    indent_level = current_indent

                item_text = re.sub(r'^\d+\. ', '', stripped)
                result.append('    ' * (current_indent // 2 + 1) + f'<li> {item_text} </li>')

            else:
                # リストの終了
                if in_ul:
                    result.append('</ul>')
                    in_ul = False
                if in_ol:
                    result.append('</ol>')
                    in_ol = False
                indent_level = 0
                result.append(line)

            i += 1

        # 最後にリストが開いていた場合は閉じる
        if in_ul:
            result.append('</ul>')
        if in_ol:
            result.append('</ol>')

        return '\n'.join(result)

    def convert_code_blocks(self, content: str) -> str:
        """コードブロックを```形式から4スペースインデント形式に変換"""
        def replace_code_block(match):
            language = match.group(1) if match.group(1) else ''
            code = match.group(2)
            # 各行に4スペースのインデントを追加
            indented_code = '\n'.join('    ' + line for line in code.split('\n'))
            return indented_code

        # 言語指定ありのコードブロック
        content = re.sub(r'```(\w+)?\n(.*?)```', replace_code_block, content, flags=re.DOTALL)

        return content

    def convert_images(self, content: str) -> str:
        """HTML形式の画像をMarkdown標準形式に変換"""
        def replace_img_tag(match):
            src = match.group(1)
            alt = match.group(2) if match.group(2) else ''
            return f'![{alt}]({src})'

        # <img src="..." alt="..." /> 形式を変換
        content = re.sub(r'<img\s+src="([^"]+)"\s+alt="([^"]*)"[^>]*/?>', replace_img_tag, content)

        return content

    def check_latex_math(self, content: str) -> bool:
        """LaTeX数式が含まれているかチェック"""
        # インライン数式 $...$
        inline_math = re.search(r'\$[^$]+\$', content)
        # ブロック数式 $$...$$
        block_math = re.search(r'\$\$.*?\$\$', content, re.DOTALL)

        return inline_math is not None or block_math is not None

    def convert_content(self, content: str) -> str:
        """本文の内容を変換"""
        # LaTeX数式のチェック
        if self.check_latex_math(content):
            self.warnings.append(
                "警告: LaTeX数式が検出されました。はてなブログでは数式表示がサポートされていないため、"
                "数式部分の変換は行われません。手動で調整してください。"
            )

        # 各種変換を実行
        content = self.convert_strikethrough(content)
        content = self.convert_lists(content)
        content = self.convert_code_blocks(content)
        content = self.convert_images(content)

        return content

    def convert_file(self, input_path: str) -> str:
        """ファイル全体を変換"""
        self.warnings = []  # 警告をリセット

        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # フロントマターと本文を分離
        if content.startswith('---\n'):
            parts = content.split('---\n', 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1]
                body = parts[2]

                # フロントマターをパース
                frontmatter = yaml.safe_load(frontmatter_text)

                # 変換実行
                converted_frontmatter = self.convert_frontmatter(frontmatter)
                converted_body = self.convert_content(body)

                # 結合
                result = f"---\n{converted_frontmatter}---\n{converted_body}"

                return result
            else:
                # フロントマターが正しく終了していない場合
                return self.convert_content(content)
        else:
            # フロントマターがない場合
            return self.convert_content(content)

    def get_warnings(self) -> List[str]:
        """変換時の警告を取得"""
        return self.warnings


def main():
    parser = argparse.ArgumentParser(
        description='Astro ブログ記事をはてなブログ形式に変換します'
    )
    parser.add_argument('input_file', help='変換する入力ファイル')
    parser.add_argument('--output', '-o', help='出力ファイル（指定なしの場合は標準出力）')

    args = parser.parse_args()

    # 入力ファイルの存在チェック
    if not Path(args.input_file).exists():
        print(f"エラー: 入力ファイル '{args.input_file}' が見つかりません。", file=sys.stderr)
        sys.exit(1)

    # 変換実行
    converter = AstroToHatenaConverter()
    try:
        result = converter.convert_file(args.input_file)

        # 警告があれば表示
        warnings = converter.get_warnings()
        for warning in warnings:
            print(warning, file=sys.stderr)

        # 出力
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(result)
            print(f"変換完了: {args.output}")
        else:
            print(result)

    except Exception as e:
        print(f"エラー: 変換中に問題が発生しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
