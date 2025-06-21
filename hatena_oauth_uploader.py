"""
はてなブログOAuth投稿ツール
OAuth認証を使用してローカルのMarkdownファイルをはてなブログに投稿するコマンドラインツール
"""

import os
import sys
import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import requests
import markdown
import re
import urllib.parse
import webbrowser
from requests_oauthlib import OAuth1Session

class HatenaBlogOAuthUploader:
    def __init__(self, config_file="hatena_oauth_config.json"):
        self.config = {}
        self.config_file = self._resolve_config_path(config_file)
        self.load_config()

        # OAuth URLs
        self.request_token_url = "https://www.hatena.com/oauth/initiate"
        self.authorization_url = "https://www.hatena.com/oauth/authorize"
        self.access_token_url = "https://www.hatena.com/oauth/token"

        # AtomPub API エンドポイント
        self.api_url = f"https://blog.hatena.ne.jp/{self.hatena_id}/{self.blog_id}/atom/entry"

    def _resolve_config_path(self, config_file):
        """設定ファイルのパスをsecretsディレクトリに解決する"""
        # secretsディレクトリのパス
        secrets_dir = Path("secrets")

        # secretsディレクトリが存在しない場合は作成
        if not secrets_dir.exists():
            secrets_dir.mkdir(parents=True, exist_ok=True)
            print(f"secretsディレクトリを作成しました: {secrets_dir.absolute()}")

        # 設定ファイルをsecretsディレクトリ内に配置
        config_path = secrets_dir / config_file

        return str(config_path)

    def load_config(self):
        """設定ファイルを読み込む"""
        if not os.path.exists(self.config_file):
            self.create_config()
            print(f"設定ファイル {self.config_file} を作成しました。")
            print("OAuth認証情報を設定してください。")
            sys.exit(1)

        with open(self.config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        try:
            oauth_config = self.config['oauth']
            self.hatena_id = oauth_config['hatena_id']
            self.blog_id = oauth_config['blog_id']
            self.consumer_key = oauth_config['consumer_key']
            self.consumer_secret = oauth_config['consumer_secret']

            # アクセストークンが存在するかチェック
            self.access_token = oauth_config.get('access_token', '')
            self.access_token_secret = oauth_config.get('access_token_secret', '')

        except KeyError as e:
            print(f"設定ファイルに {e} が設定されていません。")
            sys.exit(1)

    def create_config(self):
        """設定ファイルを作成"""
        self.config = {
            'oauth': {
                "hatena_id": "your_hatena_id",
                "blog_id": "your_blog.hatenablog.com",
                "consumer_key": "your_consumer_key",
                "consumer_secret": "your_consumer_secret",
                'access_token': '',  # 初回認証後に自動設定
                'access_token_secret': ''  # 初回認証後に自動設定
            }
        }

        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def save_access_token(self, access_token, access_token_secret):
        """アクセストークンを設定ファイルに保存"""
        self.config['oauth']['access_token'] = access_token
        self.config['oauth']['access_token_secret'] = access_token_secret

        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        self.access_token = access_token
        self.access_token_secret = access_token_secret

    def authenticate(self):
        """OAuth認証を実行"""
        if self.access_token and self.access_token_secret:
            print("既存のアクセストークンを使用します。")
            return True

        print("OAuth認証を開始します...")

        # Step 1: Request Token を取得（スコープ付き）
        oauth = OAuth1Session(
            client_key=self.consumer_key,
            client_secret=self.consumer_secret,
            callback_uri='oob'  # Out of Band
        )

        # はてなブログ投稿に必要なスコープを指定
        request_token_url_with_scope = f"{self.request_token_url}?scope=read_public,read_private,write_public,write_private"

        try:
            fetch_response = oauth.fetch_request_token(request_token_url_with_scope)
        except Exception as e:
            print(f"Request Token の取得に失敗しました: {e}")
            return False

        resource_owner_key = fetch_response.get('oauth_token')
        resource_owner_secret = fetch_response.get('oauth_token_secret')

        # Step 2: ユーザーに認証URLを開いてもらう
        authorization_url = oauth.authorization_url(self.authorization_url)
        print(f"\n以下のURLをブラウザで開いて認証してください:")
        print(f"{authorization_url}")
        print("\n認証後に表示される認証コード（PIN）を入力してください。")

        # ブラウザを自動で開く
        try:
            webbrowser.open(authorization_url)
        except:
            pass

        # ユーザーから認証コードを取得
        verifier = input("認証コード（PIN）: ").strip()

        if not verifier:
            print("認証コードが入力されていません。")
            return False

        # Step 3: Access Token を取得
        oauth = OAuth1Session(
            client_key=self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=resource_owner_key,
            resource_owner_secret=resource_owner_secret,
            verifier=verifier
        )

        try:
            oauth_tokens = oauth.fetch_access_token(self.access_token_url)
        except Exception as e:
            print(f"Access Token の取得に失敗しました: {e}")
            return False

        access_token = oauth_tokens.get('oauth_token')
        access_token_secret = oauth_tokens.get('oauth_token_secret')

        if not access_token or not access_token_secret:
            print("Access Token の取得に失敗しました。")
            return False

        # アクセストークンを保存
        self.save_access_token(access_token, access_token_secret)
        print("OAuth認証が完了しました。アクセストークンを保存しました。")
        return True

    def parse_markdown_front_matter(self, content):
        """Markdownのフロントマターを解析"""
        front_matter = {}

        # YAML front matter の解析
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                front_matter_text = parts[1].strip()
                content = parts[2].strip()

                # 簡単なYAMLパーサー（基本的なkey: valueのみ）
                for line in front_matter_text.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        front_matter[key.strip()] = value.strip().strip('"\'')

        return front_matter, content

    def markdown_to_hatena(self, markdown_content):
        """MarkdownをはてなブログHTML形式に変換"""
        # 基本的なMarkdown to HTML変換
        html = markdown.markdown(
            markdown_content,
            extensions=['extra', 'codehilite', 'toc'],
            extension_configs={
                'codehilite': {
                    'css_class': 'highlight',
                    'use_pygments': False
                }
            }
        )

        # はてなブログ特有の変換
        # コードブロックをはてな記法に変換
        html = re.sub(
            r'<pre><code class="language-(\w+)">(.*?)</code></pre>',
            r'>|\1|\n\2\n||<',
            html,
            flags=re.DOTALL
        )

        # 通常のコードブロック
        html = re.sub(
            r'<pre><code>(.*?)</code></pre>',
            r'>||\n\1\n||<',
            html,
            flags=re.DOTALL
        )

        return html

    def create_atom_entry(self, title, content, categories=None, draft=False):
        """AtomPub用のXMLエントリを作成"""
        entry = ET.Element('entry')
        entry.set('xmlns', 'http://www.w3.org/2005/Atom')
        entry.set('xmlns:app', 'http://www.w3.org/2007/app')

        # タイトル
        title_elem = ET.SubElement(entry, 'title')
        title_elem.text = title

        # 本文
        content_elem = ET.SubElement(entry, 'content')
        content_elem.set('type', 'text/html')
        content_elem.text = content

        # カテゴリ
        if categories:
            for category in categories:
                category_elem = ET.SubElement(entry, 'category')
                category_elem.set('term', category.strip())

        # 下書き設定
        if draft:
            control = ET.SubElement(entry, 'app:control')
            draft_elem = ET.SubElement(control, 'app:draft')
            draft_elem.text = 'yes'

        return ET.tostring(entry, encoding='unicode')

    def upload_entry(self, title, content, categories=None, draft=False):
        """エントリをはてなブログにアップロード"""
        if not self.access_token or not self.access_token_secret:
            print("認証が必要です。先に authenticate() を実行してください。")
            return False

        atom_entry = self.create_atom_entry(title, content, categories, draft)

        # OAuth認証セッションを作成
        oauth = OAuth1Session(
            client_key=self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret
        )

        headers = {
            'Content-Type': 'application/atom+xml; charset=utf-8'
        }

        try:
            response = oauth.post(
                self.api_url,
                data=atom_entry.encode('utf-8'),
                headers=headers
            )

            if response.status_code == 201:
                # 投稿成功
                location = response.headers.get('Location', '')
                print(f"投稿が完了しました: {location}")
                return True
            else:
                print(f"投稿に失敗しました: {response.status_code}")
                print(f"エラー内容: {response.text}")

                # 認証エラーの場合はトークンをリセット
                if response.status_code == 401:
                    print("認証エラーです。アクセストークンをリセットします。")
                    self.save_access_token('', '')

                return False

        except requests.exceptions.RequestException as e:
            print(f"通信エラー: {e}")
            return False

    def upload_file(self, file_path, draft=False):
        """Markdownファイルをアップロード"""
        file_path = Path(file_path)

        if not file_path.exists():
            print(f"ファイルが見つかりません: {file_path}")
            return False

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # フロントマターを解析
        front_matter, markdown_content = self.parse_markdown_front_matter(content)

        # タイトルを取得（フロントマターまたはファイル名から）
        title = front_matter.get('title', file_path.stem)

        # カテゴリを取得
        categories = []
        if 'categories' in front_matter:
            categories = [cat.strip() for cat in front_matter['categories'].split(',')]
        elif 'tags' in front_matter:
            categories = [tag.strip() for tag in front_matter['tags'].split(',')]

        # 下書き設定
        is_draft = front_matter.get('draft', 'false').lower() == 'true' or draft

        # Markdownをはてなブログ形式に変換
        html_content = self.markdown_to_hatena(markdown_content)

        print(f"認証方式: OAuth")
        print(f"タイトル: {title}")
        print(f"カテゴリ: {', '.join(categories) if categories else 'なし'}")
        print(f"下書き: {'はい' if is_draft else 'いいえ'}")
        print()

        # アップロード
        return self.upload_entry(title, html_content, categories, is_draft)

def main():
    parser = argparse.ArgumentParser(
        description='はてなブログOAuth投稿ツール'
    )
    parser.add_argument(
        'file',
        nargs='?',
        help='投稿するMarkdownファイルのパス'
    )
    parser.add_argument(
        '--draft',
        action='store_true',
        help='下書きとして投稿'
    )
    parser.add_argument(
        '--config',
        required=True,
        help='設定ファイルのパス'
    )
    parser.add_argument(
        '--auth',
        action='store_true',
        help='OAuth認証のみを実行（ファイル投稿は行わない）'
    )

    args = parser.parse_args()

    # アップローダーを初期化
    uploader = HatenaBlogOAuthUploader(args.config)

    # OAuth認証を実行
    if not uploader.authenticate():
        print("OAuth認証に失敗しました。")
        sys.exit(1)

    # 認証のみの場合は終了
    if args.auth:
        print("OAuth認証が完了しました。")
        return

    # ファイルが指定されていない場合
    if not args.file:
        print("投稿するファイルを指定してください。")
        print("認証のみを行う場合は --auth オプションを使用してください。")
        sys.exit(1)

    # ファイルをアップロード
    success = uploader.upload_file(args.file, args.draft)

    if success:
        print("アップロードが完了しました！")
    else:
        print("アップロードに失敗しました。")
        sys.exit(1)

if __name__ == '__main__':
    main()
