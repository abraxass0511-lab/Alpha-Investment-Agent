---
description: 시크릿/환경변수 관리 원칙 - GitHub Secrets 및 Cloudflare 환경변수만 사용
---

# 시크릿 관리 절대 원칙

> **로컬 `.env` 파일에 민감 정보를 절대 저장하지 않는다.**
> **모든 API 키, 토큰은 GitHub Secrets 또는 Cloudflare Worker 환경변수에서만 관리한다.**

---

## GitHub Actions Secrets (alpha_daily.yml에서 사용)

| Secret Name | 용도 | 사용처 |
|:--|:--|:--|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | messenger, notify_failure |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID | messenger, notify_failure |
| `FMP_API_KEY` | Financial Modeling Prep API | scanner (3,4단계) |
| `FINNHUB_API_KEY` | Finnhub API | scanner (1~4단계), sentiment (6단계 백업) |
| `KIS_APP_KEY` | 한국투자증권 앱키 | trader, rebalancer |
| `KIS_SECRET_KEY` | 한국투자증권 시크릿키 | trader, rebalancer |
| `KIS_CANO` | 계좌번호 (앞 8자리) | trader |
| `KIS_ACNT_PRDT_CD` | 계좌상품코드 | trader |
| `KIS_BASE_URL` | KIS API 베이스 URL | trader |
| `GEMINI_API_KEY` | Gemini Flash AI API | messenger (AI 인사이트) |
| `MARKETAUX_API_KEY` | MarketAux ML 심리분석 API | sentiment (5단계) |

## Cloudflare Worker 환경변수 (worker.js에서 사용)

| Variable Name | 용도 | 타입 |
|:--|:--|:--|
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | Secret |
| `TELEGRAM_CHAT_ID` | 텔레그램 채팅 ID | Secret |
| `KIS_APP_KEY` | 한국투자증권 앱키 | Secret |
| `KIS_SECRET_KEY` | 한국투자증권 시크릿키 | Secret |
| `KIS_CANO` | 계좌번호 | Secret |
| `KIS_ACNT_PRDT_CD` | 계좌상품코드 | Secret |
| `KIS_BASE_URL` | KIS API 베이스 URL | Secret |
| `GEMINI_API_KEY` | Gemini Flash AI API | Secret |
| `GITHUB_PAT` | GitHub Actions 트리거용 PAT | Secret |

## Cloudflare KV 바인딩

| Binding Name | Namespace | 용도 |
|:--|:--|:--|
| `KV` | `alpha-bot-data` | 예약 매도 상태 저장 |

---

## 규칙

1. **코드에 API 키를 하드코딩하지 않는다**
2. **`.env` 파일은 로컬 테스트용으로만 사용하며, 실제 운영은 GitHub Secrets / Cloudflare 환경변수만 사용한다**
3. **새로운 API 키가 필요하면 GitHub Secrets에 추가하고, alpha_daily.yml의 env 블록에 매핑한다**
4. **Cloudflare Worker에서 필요한 값은 Settings → Variables and Secrets에 Encrypt로 추가한다**
5. **이 문서를 항상 최신 상태로 유지한다**
