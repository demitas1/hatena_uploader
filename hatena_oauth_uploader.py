"""
はてなブログOAuth投稿ツール
OAuth認証を使用してローカルのMarkdownファイルをはてなブログに投稿するコマンドラインツール
"""

import os
import sys
import argparse
import json
import yaml
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import requests
import mistune
import re
import urllib.parse
import webbrowser
from requests_oauthlib import OAuth1Session
from dateutil import parser as date_parser
import pytz
import mimetypes
import base64


class HatenaBlogOAuthUploader:
    def __init__(self, config_file):
        self.config = {}
        self.config_file = self._resolve_config_path(config_file)
        self.load_config()

        # OAuth URLs
        self.request_token_url = "https://www.hatena.com/oauth/initiate"
        self.authorization_url = "https://www.hatena.com/oauth/authorize"
        self.access_token_url = "https://www.hatena.com/oauth/token"

        # AtomPub API エンドポイント
        self.api_url = f"https://blog.hatena.ne.jp/{self.hatena_id}/{self.blog_id}/atom/entry"

        # 画像アップロード用エンドポイント（はてなフォトライフ用）
        self.image_upload_url = f"https://f.hatena.ne.jp/atom/post/{self.hatena_id}"

    def _resolve_config_path(self, config_file):
        """設定ファイルのパスを解決する (将来拡張用)"""
        config_path = config_file
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

                try:
                    # PyYAMLを使用してYAMLを解析
                    front_matter = yaml.safe_load(front_matter_text)

                    # front_matterがNoneの場合は空の辞書を設定
                    if front_matter is None:
                        front_matter = {}

                except yaml.YAMLError as e:
                    print(f"YAML解析エラー: {e}")
                    # エラーが発生した場合は空の辞書を返す
                    front_matter = {}

        return front_matter, content

    def parse_date(self, date_string):
        """日付文字列をISO 8601形式に変換"""
        if not date_string:
            return None

        try:
            # 様々な日付フォーマットを解析
            parsed_date = date_parser.parse(date_string)

            # タイムゾーンが設定されていない場合はJSTを設定
            if parsed_date.tzinfo is None:
                jst = pytz.timezone('Asia/Tokyo')
                parsed_date = jst.localize(parsed_date)

            # ISO 8601形式で返す
            return parsed_date.isoformat()
        except Exception as e:
            print(f"日付の解析に失敗しました: {date_string} - {e}")
            return None

    def markdown_to_html(self, markdown_content, hatena=False):
        """MarkdownをはてなブログHTML形式に変換"""
        # 基本的なMarkdown to HTML変換
        html = mistune.html(markdown_content)

        # はてなブログ特有の変換
        if hatena:
            # コードブロックをはてな記法に変換
            html = re.sub(
                r'<pre><code class="language-(\w+)">(.*?)</code></pre>',
                r'<blockquote>\n\2\n</blockquote>',
                html,
                flags=re.DOTALL
            )

            # 通常のコードブロック
            html = re.sub(
                r'<pre><code>(.*?)</code></pre>',
                r'<blockquote>\n\1\n</blockquote>',
                html,
                flags=re.DOTALL
            )

        return html

    def create_atom_entry(self,
            title,
            content,
            categories=None,
            draft=False,
            published_date=None,
            updated_date=None,
            author=None,
            summary=None,
            ):

        """AtomPub用のXMLエントリを作成"""
        entry = ET.Element('entry')
        entry.set('xmlns', 'http://www.w3.org/2005/Atom')
        entry.set('xmlns:app', 'http://www.w3.org/2007/app')

        # タイトル
        title_elem = ET.SubElement(entry, 'title')
        title_elem.text = title

        # 投稿者
        if author:
            author_elem = ET.SubElement(entry, 'author')
            name_elem = ET.SubElement(author_elem, 'name')
            name_elem.text = author

        # 要約
        if summary:
            summary_elem = ET.SubElement(entry, 'summary')
            summary_elem.text = summary

        # 本文
        content_elem = ET.SubElement(entry, 'content')
        content_elem.set('type', 'text/html')
        content_elem.text = content

        # 公開日時
        if published_date:
            published_elem = ET.SubElement(entry, 'published')
            published_elem.text = published_date

        # 更新日時
        if updated_date:
            updated_elem = ET.SubElement(entry, 'updated')
            updated_elem.text = updated_date

        # カテゴリ
        if categories:
            for category in categories:
                category_elem = ET.SubElement(entry, 'category')
                category_value = category.strip()
                category_elem.set('term', category_value)

        # 下書き設定
        if draft:
            control = ET.SubElement(entry, 'app:control')
            draft_elem = ET.SubElement(control, 'app:draft')
            draft_elem.text = 'yes'

        return ET.tostring(entry, encoding='unicode')

    def upload_entry(self,
            title,
            content,
            categories=None,
            draft=False,
            published_date=None,
            updated_date=None,
            author=None,
            summary=None,
            preview=False):

        """エントリをはてなブログにアップロード"""
        if not self.access_token or not self.access_token_secret:
            print("認証が必要です。先に authenticate() を実行してください。")
            return False

        atom_entry = self.create_atom_entry(
            title,
            content,
            categories,
            draft,
            published_date,
            updated_date,
            author,
            summary)

        if preview:
            return True

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

    def upload_file(self, file_path, draft=False, preview=False):
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
            categories = front_matter['categories']
        elif 'tags' in front_matter:
            categories = front_matter['tags']

        # 下書き設定
        is_draft = front_matter.get('draft', False)

        # 日付情報を取得・変換
        published_date = None
        updated_date = None

        # 公開日時（date または published）
        date_value = front_matter.get('date') or front_matter.get('published')
        if date_value:
            published_date = self.parse_date(date_value)

        # 更新日時
        updated_value = front_matter.get('updated')
        if updated_value:
            updated_date = self.parse_date(updated_value)

        # 投稿者情報
        author = front_matter.get('author')

        # 要約情報（summary または excerpt）
        summary = front_matter.get('summary') or front_matter.get('excerpt')

        # Markdownをはてなブログ形式に変換
        html_content = self.markdown_to_html(markdown_content, hatena=False)

        print(f"認証方式: OAuth")
        print(f"タイトル: {title}")
        print(f"カテゴリ: {', '.join(categories) if categories else 'なし'}")
        print(f"下書き: {'はい' if is_draft else 'いいえ'}")
        if author:
            print(f"投稿者: {author}")
        if summary:
            print(f"要約: {summary}")
        if published_date:
            print(f"公開日時: {published_date}")
        if updated_date:
            print(f"更新日時: {updated_date}")
        print()

        # プレビュー
        if preview:
            print(html_content)

        # アップロード
        return self.upload_entry(
            title,
            html_content,
            categories,
            is_draft,
            published_date,
            updated_date,
            author,
            summary,
            preview=preview)


    def upload_image(self, image_path, verbose=False, output_file=None):
        """画像をはてなフォトライフにアップロード"""
        image_path = Path(image_path)

        # ファイル存在確認
        if not image_path.exists():
            print(f"画像ファイルが見つかりません: {image_path}")
            return None

        # MIMEタイプチェック
        mime_type, _ = mimetypes.guess_type(str(image_path))
        if not mime_type:
            print(f"MIMEタイプを判定できません: {image_path}")
            return None
        if verbose:
            print(f'MIME type = {mime_type}')

        # 画像ファイルチェック (jpg, png のみ許可)
        if not mime_type.startswith('image/'):
            print(f"画像ファイルではありません: {image_path} (MIME: {mime_type})")
            return None

        # jpg, png のみ許可
        if mime_type not in ['image/jpeg', 'image/png']:
            print(f"サポートされていない画像形式です: {mime_type} (jpg, png のみ対応)")
            return None

        # 認証チェック
        if not self.access_token or not self.access_token_secret:
            print("認証が必要です。先に authenticate() を実行してください。")
            return None

        # 画像ファイルを読み込み
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
        except Exception as e:
            print(f"画像ファイルの読み込みに失敗しました: {e}")
            return None

        # Base64エンコード
        encoded_image = base64.b64encode(image_data).decode('utf-8')

        # はてなフォトライフ用のXMLエントリを作成
        entry_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom">
    <title>{image_path.name}</title>
    <content mode="base64" type="{mime_type}">{encoded_image}</content>
</entry>'''

        # OAuth認証セッションを作成
        oauth = OAuth1Session(
            client_key=self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret
        )

        # ヘッダーの設定
        headers = {
            'Content-Type': 'application/atom+xml; charset=utf-8'
        }

        try:
            response = oauth.post(
                self.image_upload_url,
                data=entry_xml.encode('utf-8'),
                headers=headers
            )

            if response.status_code == 201:
                if verbose:
                    # デバッグ用: レスポンス全体を表示
                    print("\n=== デバッグ: XMLレスポンス全体 ===")
                    print(response.text)
                    print("=== デバッグ終了 ===\n")

                # XMLレスポンスを解析して画像URLを取得
                try:
                    root = ET.fromstring(response.text)

                    if verbose:
                        # デバッグ用: XMLの構造を表示
                        print("=== XMLの構造解析 ===")
                        for elem in root.iter():
                            print(f"要素: {elem.tag}, 属性: {elem.attrib}, テキスト: {elem.text}")
                        print("=== 構造解析終了 ===\n")

                    # はてな独自の名前空間から画像URLを取得
                    hatena_ns = 'http://www.hatena.ne.jp/info/xmlns#'

                    # 各サイズの画像URLを取得
                    imageurl_elem = root.find(f'.//{{{hatena_ns}}}imageurl')
                    imageurl_medium_elem = root.find(f'.//{{{hatena_ns}}}imageurlmedium')
                    imageurl_small_elem = root.find(f'.//{{{hatena_ns}}}imageurlsmall')

                    # 結果データを集約
                    result_data = {
                        "success": True,
                        "filename": image_path.name,
                        "urls": {}
                    }

                    if imageurl_elem is not None and imageurl_elem.text:
                        original_url = imageurl_elem.text
                        result_data["urls"]["original"] = original_url

                        if imageurl_medium_elem is not None and imageurl_medium_elem.text:
                            medium_url = imageurl_medium_elem.text
                            result_data["urls"]["medium"] = medium_url

                        if imageurl_small_elem is not None and imageurl_small_elem.text:
                            small_url = imageurl_small_elem.text
                            result_data["urls"]["small"] = small_url

                        result_data["html_tag"] = f'<img src="{original_url}" alt="{image_path.name}">'

                        # 出力処理
                        if output_file:
                            # JSONファイルに保存
                            with open(output_file, 'w', encoding='utf-8') as f:
                                json.dump(result_data, f, indent=2, ensure_ascii=False)
                            print(f"結果を{output_file}に保存しました")
                        else:
                            # 標準出力に表示
                            print("=== 画像アップロード完了 ===")
                            print(f"オリジナル画像URL: {original_url}")

                            if "medium" in result_data["urls"]:
                                print(f"中サイズ画像URL: {result_data['urls']['medium']}")

                            if "small" in result_data["urls"]:
                                print(f"小サイズ画像URL: {result_data['urls']['small']}")

                            print(f"\nブログ記事で使用する場合:")
                            print(result_data["html_tag"])
                            print("========================\n")

                        return original_url
                    else:
                        # 従来の方法でのフォールバック
                        content_elem = root.find('.//{http://www.w3.org/2005/Atom}content')
                        if content_elem is not None and 'src' in content_elem.attrib:
                            image_url = content_elem.attrib['src']
                            print(f"画像のアップロードが完了しました: {image_url}")
                            return image_url
                        else:
                            # alternativeとしてlink要素を確認
                            link_elem = root.find('.//{http://www.w3.org/2005/Atom}link[@rel="edit-media"]')
                            if link_elem is not None and 'href' in link_elem.attrib:
                                edit_url = link_elem.attrib['href']
                                print(f"画像のアップロードが完了しました: {edit_url}")
                                return edit_url
                            else:
                                # location headerから取得を試行
                                location = response.headers.get('Location', '')
                                if location:
                                    print(f"画像のアップロードが完了しました: {location}")
                                    return location
                                else:
                                    print("XMLレスポンスから画像URLを取得できませんでした")
                                    return None
                except ET.ParseError as e:
                    print(f"XMLレスポンスの解析に失敗しました: {e}")
                    print(f"レスポンス: {response.text}")
                    return None
            else:
                print(f"画像のアップロードに失敗しました: {response.status_code}")
                print(f"エラー内容: {response.text}")

                # 認証エラーの場合はトークンをリセット
                if response.status_code == 401:
                    print("認証エラーです。アクセストークンをリセットします。")
                    self.save_access_token('', '')

                return None

        except requests.exceptions.RequestException as e:
            print(f"通信エラー: {e}")
            return None

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
        '--preview',
        action='store_true',
        help='変換のみ行い投稿をしない'
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
        '--auth-only',
        action='store_true',
        help='OAuth認証のみを実行（ファイル投稿は行わない）'
    )
    parser.add_argument(
        '--image',
        action='store_true',
        help='ファイルを画像として扱い、画像アップロードを行う'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='詳細なデバッグ情報を表示'
    )
    parser.add_argument(
        '--output',
        help='結果をJSON形式で保存するファイルパス'
    )

    args = parser.parse_args()

    # アップローダーを初期化
    uploader = HatenaBlogOAuthUploader(args.config)

    # OAuth認証を実行
    if not uploader.authenticate():
        print("OAuth認証に失敗しました。")
        sys.exit(1)

    # 認証のみの場合は終了
    if args.auth_only:
        print("OAuth認証が完了しました。")
        return

    # ファイルが指定されていない場合
    if not args.file:
        print("投稿するファイルを指定してください。")
        print("認証のみを行う場合は --auth-only オプションを使用してください。")
        sys.exit(1)

    # 画像アップロードまたはブログ投稿の分岐処理
    if args.image:
        # 画像アップロード
        image_url = uploader.upload_image(args.file, args.verbose, args.output)
        if image_url:
            if not args.output:  # 標準出力の場合のみ表示
                print(f"画像アップロードが完了しました！")
        else:
            print("画像アップロードに失敗しました。")
            sys.exit(1)
    else:
        # ブログ投稿
        success = uploader.upload_file(
            args.file,
            draft=args.draft,
            preview=args.preview)
        if success:
            print("ブログ投稿が完了しました！")
        else:
            print("ブログ投稿に失敗しました。")
            sys.exit(1)

if __name__ == '__main__':
    main()
