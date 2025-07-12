import os
import sys
import json
import webbrowser
from requests_oauthlib import OAuth1Session


class ConfigManager:
    def __init__(self, config_file):
        self.config = {}
        self.config_file = self._resolve_config_path(config_file)

        # OAuth URLs
        self.request_token_url = "https://www.hatena.com/oauth/initiate"
        self.authorization_url = "https://www.hatena.com/oauth/authorize"
        self.access_token_url = "https://www.hatena.com/oauth/token"

        self.load_config()

    def _resolve_config_path(self, config_file):
        """設定ファイルのパスを解決する"""
        return str(config_file)

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

    def get_oauth_credentials(self):
        """OAuth認証情報を取得"""
        return {
            'hatena_id': self.hatena_id,
            'blog_id': self.blog_id,
            'consumer_key': self.consumer_key,
            'consumer_secret': self.consumer_secret,
            'access_token': self.access_token,
            'access_token_secret': self.access_token_secret
        }

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
