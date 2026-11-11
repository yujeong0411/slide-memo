"""앱 안에서 여는 블로그 링크는 여기 한 곳에서만 관리한다.

도메인을 붙이면 Vercel에서 nursecoder.vercel.app → 새 도메인으로 영구 리디렉션한다.
그러면 이미 설치된 앱도 그대로 맞는 곳으로 가므로 이 값은 바꾸지 않아도 된다."""

BLOG_URL = "https://nursecoder.vercel.app"
PRIVACY_URL = BLOG_URL + "/tools/slide-memo/privacy"
