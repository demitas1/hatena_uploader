# Hatena Blog posting tool

## Setup

```console
python3 -m venv venv
source venv/bin/activate

pip install requests markdown requests-oauthlib
```

## Usage

1. Create config file

```console
python hatena_oauth_uploader.py --config hatena.json
```

New `secrets/hatena.json` file is created.

2. Fill API key in JSON file

```json
{
  "oauth": {
    "hatena_id": "your_hatena_id",
    "blog_id": "your_blog.hatenablog.com",
    "consumer_key": "your_consumer_key",
    "consumer_secret": "your_consumer_secret",
    "access_token": "",
    "access_token_secret": ""
  }
}
```

3. Authentication

```console
python hatena_oauth_uploader.py --auth --config hatena.json
```

4. Post a markdown file (--config is required)

```console
python hatena_oauth_uploader.py article.md --config hatena.json
```


## License

MIT
