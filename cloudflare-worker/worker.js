/**
 * Alpha Telegram Bot - Cloudflare Worker
 * Telegram menu instant response (Webhook)
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Webhook 등록/해제 관리
    if (url.pathname === "/setup-webhook") {
      try {
        const workerUrl = url.origin;
        const telegramUrl = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/setWebhook`;
        const r = await fetch(telegramUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: workerUrl }),
        });
        const data = await r.json();
        return new Response(JSON.stringify({
          action: "setWebhook",
          webhook_url: workerUrl,
          telegram_response: data,
        }, null, 2), { headers: { "Content-Type": "application/json" } });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" },
        });
      }
    }

    if (url.pathname === "/webhook-status") {
      try {
        const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/getWebhookInfo`);
        const data = await r.json();
        return new Response(JSON.stringify(data, null, 2), {
          headers: { "Content-Type": "application/json" },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" },
        });
      }
    }

    if (url.pathname === "/debug") {
      try {
        const results = {};
        const token = await getKisToken(env);
        results.token = token ? "OK" : "FAIL";
        
        if (token) {
          const balUrl = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance`;
          const balParams = new URLSearchParams({
            CANO: env.KIS_CANO, ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
            OVRS_EXCG_CD: "NASD", TR_CRCY_CD: "USD",
            CTX_AREA_FK200: "", CTX_AREA_NK200: "",
          });
          const balR = await fetch(`${balUrl}?${balParams}`, {
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              appkey: env.KIS_APP_KEY, appsecret: env.KIS_SECRET_KEY,
              "tr_id": "VTTS3012R",
            },
          });
          results.balance_raw = await balR.json();

          const bpUrl = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-psamount`;
          const bpParams = new URLSearchParams({
            CANO: env.KIS_CANO, ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
            OVRS_EXCG_CD: "NASD", OVRS_ORD_UNPR: "0", ITEM_CD: "AAPL",
          });
          const bpR = await fetch(`${bpUrl}?${bpParams}`, {
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              appkey: env.KIS_APP_KEY, appsecret: env.KIS_SECRET_KEY,
              "tr_id": "VTTS3007R",
            },
          });
          results.buying_power_raw = await bpR.json();

          // Check KV pending sell
          if (env.KV) {
            results.pending_sell = await env.KV.get("pending_sell");
          }
        }
        
        return new Response(JSON.stringify(results, null, 2), {
          headers: { "Content-Type": "application/json" },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    if (url.pathname === "/api/portfolio") {
      try {
        const authHeader = request.headers.get("Authorization") || "";
        if (authHeader !== `Bearer ${env.WORKER_API_KEY || "alpha-internal"}`) {
          return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
        }

        const holdings = await getBalance(env);
        const bp = await getBuyingPower(env);

        // 1차: 매수가능금액 조회
        let buyingPower = bp ? (bp.ord_psbl_frcr_amt || "0") : "0";

        // 2차: $0이면 체결기준 예수금 조회(장 외 시간에도 동작)
        if (parseFloat(buyingPower) <= 0) {
          const deposit = await getDeposit(env);
          if (deposit && deposit.usd_amt) {
            buyingPower = deposit.usd_amt;
          }
        }

        const result = {
          holdings: [],
          buying_power: buyingPower,
          api_error: false,
          error_detail: "",
        };

        // ★ KIS 잔고 조회 실패 시 에러 플래그 설정 (클라이언트가 폴백 판단용)
        if (!holdings) {
          result.api_error = true;
          result.error_detail = "KIS 잔고 조회 실패 (토큰 만료 또는 서버 점검)";
        } else if (holdings.length > 0) {
          result.holdings = holdings
            .filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0)
            .map(h => ({
              symbol: h.ovrs_pdno || "?",
              qty: parseInt(h.ovrs_cblc_qty || "0"),
              buy_avg: parseFloat(h.pchs_avg_pric || "0"),
              current: parseFloat(h.now_pric2 || "0"),
              pnl_rate: parseFloat(h.evlu_pfls_rt || "0"),
              pnl_amt: parseFloat(h.frcr_evlu_pfls_amt || "0"),
            }));
        }

        return new Response(JSON.stringify(result), {
          headers: { "Content-Type": "application/json" },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" },
        });
      }
    }

    if (url.pathname === "/api/sell" && request.method === "POST") {
      try {
        const authHeader = request.headers.get("Authorization") || "";
        if (authHeader !== `Bearer ${env.WORKER_API_KEY || "alpha-internal"}`) {
          return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
        }

        const body = await request.json();
        const { symbol, qty, price } = body;
        if (!symbol || !qty || !price) {
          return new Response(JSON.stringify({ error: "Missing symbol/qty/price" }), { status: 400 });
        }

        const success = await sellOrder(env, symbol, parseInt(qty), String(price));
        return new Response(JSON.stringify({ success, symbol, qty, price }), {
          headers: { "Content-Type": "application/json" },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" },
        });
      }
    }

    if (request.method === "POST") {
      try {
        const update = await request.json();
        await handleUpdate(update, env);
      } catch (e) {
        console.error("Error:", e);
      }
    }
    return new Response("OK");
  },

  // Cron Trigger: market open + 체결 확인 폴링
  async scheduled(event, env, ctx) {
    try {
      if (!isTradingDay(new Date())) return;

      // === A. 체결 확인 폴링 (5분 간격 cron에서 실행) ===
      const fillPend = await env.KV.get("pending_fill_check");
      if (fillPend) {
        const fillData = JSON.parse(fillPend);
        const etHour = getETHour();

        // 체결 내역 조회 (장 마감 시에도 최종 확인 실행)
        const orders = await checkOrderFills(env);

        // API 호출 실패 시 에러 알림 (조용히 넘기지 않음)
        if (!orders) {
          // 장 마감이면 정리하면서 실패 알림
          if (etHour >= 16 && etHour < 21) {
            await sendMessage(env, "\u26a0\ufe0f *[\uccb4\uacb0 \ud655\uc778 \uc2e4\ud328]*\n\n\uc7a5 \ub9c8\uac10\uae4c\uc9c0 \uccb4\uacb0 \ub0b4\uc5ed \uc870\ud68c\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.\nKIS API \uc751\ub2f5 \uc624\ub958\uc785\ub2c8\ub2e4, \ub300\ud45c\ub2d8.\n\n\ud83d\udcb1 KIS \uc571\uc5d0\uc11c \uc9c1\uc811 \uccb4\uacb0 \uc5ec\ubd80\ub97c \ud655\uc778\ud574 \uc8fc\uc138\uc694.", REPLY_KEYBOARD);
            await env.KV.delete("pending_fill_check");
          }
          // 장 중이면 → fill check만 스킵, 아래 예약 주문은 계속 실행
        } else {
          const symbols = fillData.symbols || [];
          let filledAll = true;
          let msg = "\ud83d\udcca *[\uccb4\uacb0 \uc54c\ub9bc]*\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n";
          let filledCount = 0;

          if (orders.length > 0) {
            for (const ord of orders) {
              const sym = ord.pdno || ord.ovrs_pdno || "?";
              if (symbols.length > 0 && !symbols.includes(sym)) continue;

              const side = ord.sll_buy_dvsn_cd === "02" ? "\ub9e4\uc218" : "\ub9e4\ub3c4";
              const ordQty = parseInt(ord.ord_qty || ord.ft_ord_qty || "0");
              const fillQty = parseInt(ord.ccld_qty || ord.ft_ccld_qty || ord.tot_ccld_qty || "0");
              const fillPrice = ord.avg_prvs || ord.ft_ccld_unpr3 || "0";

              if (fillQty > 0) {
                filledCount++;
                const emoji = side === "\ub9e4\uc218" ? "\u2705" : "\ud83d\udd3b";
                msg += `${emoji} *${sym}* ${side} \uccb4\uacb0 \uc644\ub8cc!\n`;
                msg += `   \ud83d\udcca ${fillQty}\uc8fc \u00d7 $${parseFloat(fillPrice).toFixed(2)}\n\n`;
              } else {
                filledAll = false;
              }
            }
          }

          if (filledCount > 0 && filledAll) {
            // 전부 체결 → 알림 보내고 KV 삭제
            await sendMessage(env, msg, REPLY_KEYBOARD);
            await env.KV.delete("pending_fill_check");
          } else if (filledCount > 0 && !filledAll) {
            // 일부만 체결 → 체결된 것 알리고 계속 대기
            msg += "_\ub098\uba38\uc9c0 \uc885\ubaa9 \uccb4\uacb0 \ub300\uae30 \uc911..._";
            await sendMessage(env, msg, REPLY_KEYBOARD);
          } else if (etHour >= 16 && etHour < 21) {
            // 장 마감인데 체결 감지 못함 → 최종 알림 후 정리
            let closeMsg = "\ud83d\udd52 *[\uc7a5 \ub9c8\uac10 \uccb4\uacb0 \ud655\uc778]*\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n";
            if (orders.length === 0) {
              closeMsg += "\u26a0\ufe0f \uc624\ub298 \uc8fc\ubb38 \ub0b4\uc5ed\uc774 \uc870\ud68c\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.\n";
            } else {
              closeMsg += "\u26a0\ufe0f \uccb4\uacb0 \uac10\uc9c0\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.\n";
              closeMsg += `\ud83d\udcdd \uc870\ud68c\ub41c \uc8fc\ubb38: ${orders.length}\uac74\n`;
              if (orders[0]) {
                const keys = Object.keys(orders[0]).join(", ");
                closeMsg += `\ud83d\udd0d \uc751\ub2f5 \ud544\ub4dc: _${keys.substring(0, 200)}_\n`;
              }
            }
            closeMsg += "\n\ud83d\udcb1 KIS \uc571\uc5d0\uc11c \uc9c1\uc811 \ud655\uc778\ud574 \uc8fc\uc138\uc694, \ub300\ud45c\ub2d8.";
            await sendMessage(env, closeMsg, REPLY_KEYBOARD);
            await env.KV.delete("pending_fill_check");
          }
          // 장 중 + filledCount === 0 → 다음 cron에서 재시도 (fill check만)
        }
      }

      // === B. 예약 주문 실행 (항상 독립적으로 체크) ===

      // 1. 긴급 전량 매도 예약 실행
      const sellPend = await env.KV.get("pending_sell");
      if (sellPend) {
        const data = JSON.parse(sellPend);
        if (data.type === "sell_all") {
          const result = await executeEmergencySell(env);
          await sendMessage(env, "\u23f0 *[\uc608\uc57d \ub9e4\ub3c4 \uc2e4\ud589]*\n\n" + result, REPLY_KEYBOARD);
        }
        await env.KV.delete("pending_sell");
      }

      // 2. 포트폴리오 승인 매수/매도 예약 실행
      const appPend = await env.KV.get("pending_approval");
      if (appPend) {
        const data = JSON.parse(appPend);
        if (data.type === "approval") {
          const result = await executeApproval(env);
          if (typeof result === "string") {
            await sendMessage(env, "\u23f0 *[\uc608\uc57d \uc2b9\uc778]*\n\n" + result, REPLY_KEYBOARD);
          } else {
            await sendMessage(env, "\u23f0 *[\uc608\uc57d \uc2b9\uc778 \u2192 \uc8fc\ubb38 \uc811\uc218]*\n\n" + result.msg, REPLY_KEYBOARD);
            // KV에 체결 확인 대상 저장 → 5분 간격 cron이 확인
            await saveFillCheckToKV(env, result.orderedSymbols);
          }
        }
        await env.KV.delete("pending_approval");
      }
    } catch (e) {
      await sendMessage(env, "\u26a0\ufe0f \uc608\uc57d \uc2e4\ud589 \uc911 \uc5d0\ub7ec: " + e.message, REPLY_KEYBOARD);
    }
  }
};

// === Telegram API ===
async function sendMessage(env, text, replyMarkup) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: env.TELEGRAM_CHAT_ID,
    text: text.substring(0, 4096),
    parse_mode: "Markdown",
  };
  if (replyMarkup) body.reply_markup = replyMarkup;
  
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const REPLY_KEYBOARD = {
  keyboard: [
    ["\ud83d\udcca \uc804\uccb4 \uc218\uc775\ub960", "\ud83d\udcc8 \uc885\ubaa9\ubcc4 \uc218\uc775\ub960"],
    ["\ud83d\udcb5 \uc608\uc218\uae08 \ud604\ud669", "\ud83d\udcb0 \uc2e4\uc2dc\uac04 \uc794\uace0"],
    ["\ud83d\udd0d \uc624\ub298\uc790 \uc2a4\uce94", "\ud83d\uded1 \uae34\uae09 \uc804\ub7c9 \ub9e4\ub3c4"],
  ],
  resize_keyboard: true,
  is_persistent: true,
};

// === KIS API ===
// 토큰 규칙: 유효기간 24시간, 재발급은 6시간 이후부터 가능
// 전략: KV에 저장 (24시간 자동 만료) → Worker 재시작해도 불필요한 재발급 방지
let _cachedToken = null;
let _tokenIssuedAt = 0;
const TOKEN_TTL = 23 * 3600 * 1000; // 23시간 (24시간 유효 - 1시간 여유)
const KV_TOKEN_KEY = "kis_access_token";

async function getKisToken(env, forceRefresh = false) {
  const now = Date.now();

  // 1차: 인메모리 캐시 (같은 Worker 인스턴스 내 재사용)
  if (!forceRefresh && _cachedToken && (now - _tokenIssuedAt) < TOKEN_TTL) {
    return _cachedToken;
  }

  // 2차: KV에서 토큰 로드 (24시간 자동 만료, Worker 재시작 간 유지)
  if (!forceRefresh && env.KV) {
    try {
      const kvData = await env.KV.get(KV_TOKEN_KEY);
      if (kvData) {
        const parsed = JSON.parse(kvData);
        if (parsed.token && (now - parsed.issued_at) < TOKEN_TTL) {
          _cachedToken = parsed.token;
          _tokenIssuedAt = parsed.issued_at;
          return _cachedToken;
        }
      }
    } catch {}
  }

  // 3차: 새 토큰 발급 (6시간 재발급 제한 주의)
  try {
    const url = `${env.KIS_BASE_URL}/oauth2/tokenP`;
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "client_credentials",
        appkey: env.KIS_APP_KEY,
        appsecret: env.KIS_SECRET_KEY,
      }),
    });
    const data = await r.json();

    if (data.access_token) {
      _cachedToken = data.access_token;
      _tokenIssuedAt = now;

      // KV에 저장 (24시간 후 자동 만료 — 영구 저장 아님)
      if (env.KV) {
        try {
          await env.KV.put(KV_TOKEN_KEY, JSON.stringify({
            token: _cachedToken,
            issued_at: _tokenIssuedAt,
          }), { expirationTtl: 86400 }); // 24시간 후 KV에서 자동 삭제
        } catch {}
      }

      return _cachedToken;
    } else {
      console.log("Token issue failed:", data.error_description || JSON.stringify(data));
      // 토큰 발급 실패 시 KV의 기존 토큰을 그래도 시도 (만료됐더라도)
      if (env.KV) {
        try {
          const kvData = await env.KV.get(KV_TOKEN_KEY);
          if (kvData) {
            const parsed = JSON.parse(kvData);
            if (parsed.token) {
              _cachedToken = parsed.token;
              _tokenIssuedAt = parsed.issued_at || 0;
              return _cachedToken;
            }
          }
        } catch {}
      }
      return null;
    }
  } catch (e) {
    console.log("Token fetch error:", e.message);
    return _cachedToken; // 네트워크 에러 시 기존 캐시 반환
  }
}

async function getBalance(env, _retry = false) {
  const token = await getKisToken(env);
  if (!token) return null;

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance`;
  const params = new URLSearchParams({
    CANO: env.KIS_CANO,
    ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
    OVRS_EXCG_CD: "NASD",
    TR_CRCY_CD: "USD",
    CTX_AREA_FK200: "",
    CTX_AREA_NK200: "",
  });

  const r = await fetch(`${url}?${params}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTS3012R",
    },
  });

  const data = await r.json();
  if (data.rt_cd === "0") return data.output1 || [];
  // Token expired - force refresh and retry ONCE
  if (!_retry) {
    _cachedToken = null;
    _tokenIssuedAt = 0;
    return getBalance(env, true);
  }
  return null;
}

async function getBuyingPower(env, _retry = false) {
  const token = await getKisToken(env);
  if (!token) return null;

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-psamount`;
  const params = new URLSearchParams({
    CANO: env.KIS_CANO,
    ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
    OVRS_EXCG_CD: "NASD",
    OVRS_ORD_UNPR: "0",
    ITEM_CD: "AAPL",
  });

  const r = await fetch(`${url}?${params}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTS3007R",
    },
  });

  const data = await r.json();
  if (data.rt_cd === "0") {
    const output = data.output || {};
    return {
      ord_psbl_frcr_amt: output.ord_psbl_frcr_amt || output.ovrs_ord_psbl_amt || "0",
    };
  }
  // Token expired - force refresh and retry ONCE
  if (!_retry) {
    _cachedToken = null;
    _tokenIssuedAt = 0;
    return getBuyingPower(env, true);
  }
  return null;
}

async function getDeposit(env, _retry = false) {
  const token = await getKisToken(env);
  if (!token) return null;

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-present-balance`;
  const params = new URLSearchParams({
    CANO: env.KIS_CANO,
    ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
    WCRC_FRCR_DVSN_CD: "01",
    NATN_CD: "840",
    TR_MKET_CD: "00",
    INQR_DVSN_CD: "00",
  });

  const r = await fetch(`${url}?${params}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTRP6504R",
    },
  });

  const data = await r.json();
  if (data.rt_cd === "0") {
    // output2: 통화별 예수금, USD의 frcr_dncl_amt_2가 달러 예수금
    const currencies = data.output2 || [];
    for (const c of currencies) {
      if (c.crcy_cd === "USD" && parseFloat(c.frcr_dncl_amt_2 || "0") > 0) {
        return { usd_amt: c.frcr_dncl_amt_2 };
      }
    }
    // USD가 없으면 output3의 전체 금액 사용
    const summary = data.output3 || {};
    if (summary.frcr_evlu_tota || summary.tot_asst_amt) {
      return { usd_amt: summary.frcr_evlu_tota || summary.tot_asst_amt || "0" };
    }
    return null;
  }
  if (!_retry) {
    _cachedToken = null;
    _tokenIssuedAt = 0;
    return getDeposit(env, true);
  }
  return null;
}

async function sellOrder(env, symbol, qty, price) {
  const token = await getKisToken(env);
  if (!token) return false;

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTT1006U",
    },
    body: JSON.stringify({
      CANO: env.KIS_CANO,
      ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
      OVRS_EXCG_CD: "NASD",
      PDNO: symbol,
      ORD_QTY: String(qty),
      OVRS_ORD_UNPR: String(price),
      ORD_SVR_DVSN_CD: "0",
      ORD_DVSN: "00",
    }),
  });

  const data = await r.json();
  return data.rt_cd === "0";
}

async function buyOrder(env, symbol, qty, price) {
  const token = await getKisToken(env);
  if (!token) return false;

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTT1002U",
    },
    body: JSON.stringify({
      CANO: env.KIS_CANO,
      ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
      OVRS_EXCG_CD: "NASD",
      PDNO: symbol,
      ORD_QTY: String(qty),
      OVRS_ORD_UNPR: String(price),
      ORD_SVR_DVSN_CD: "0",
      ORD_DVSN: "00",
    }),
  });

  const data = await r.json();
  return data.rt_cd === "0";
}

// === 체결 확인 함수 (KIS 주문체결내역 조회) ===
async function checkOrderFills(env) {
  const token = await getKisToken(env);
  if (!token) return null;

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-ccnl`;
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const params = new URLSearchParams({
    CANO: env.KIS_CANO,
    ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
    PDNO: "",
    ORD_STRT_DT: today,
    ORD_END_DT: today,
    SLL_BUY_DVSN: "00",
    CCLD_NCCS_DVSN: "00",
    OVRS_EXCG_CD: "",
    SORT_SQN: "DS",
    ORD_DT: "",
    ORD_GNO_BRNO: "",
    ODNO: "",
    CTX_AREA_NK200: "",
    CTX_AREA_FK200: "",
  });

  const r = await fetch(`${url}?${params}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTS3035R",
    },
  });

  const data = await r.json();
  if (data.rt_cd === "0") {
    return data.output || [];
  }
  return null;
}

// KV에 체결 확인 대상 저장 (cron이 5분 간격으로 확인)
async function saveFillCheckToKV(env, orderedSymbols) {
  if (!env.KV || !orderedSymbols || orderedSymbols.length === 0) return;
  await env.KV.put("pending_fill_check", JSON.stringify({
    symbols: orderedSymbols,
    ordered_at: new Date().toISOString(),
  }));
}

async function executeApproval(env) {
  try {
    // 1. GitHub에서 최종 추천 종목 조회
    const ts = Date.now();
    const picksUrl = `https://raw.githubusercontent.com/abraxass0511-lab/Alpha-Investment-Agent/main/output_reports/final_picks_latest.csv?t=${ts}`;
    const rebalUrl = `https://raw.githubusercontent.com/abraxass0511-lab/Alpha-Investment-Agent/main/output_reports/rebalance_recommendations.json?t=${ts}`;

    // 매수 후보 파싱 (final_picks CSV)
    let buyStocks = [];
    const picksResp = await fetch(picksUrl);
    if (picksResp.ok) {
      const csv = await picksResp.text();
      const lines = csv.trim().split("\n");
      if (lines.length > 1) {
        const h = lines[0].split(",");
        const si = h.indexOf("Symbol");
        const pi = h.indexOf("Price");
        for (let i = 1; i < lines.length; i++) {
          const c = lines[i].split(",");
          if (si >= 0 && c[si]) {
            buyStocks.push({ symbol: c[si].trim(), price: parseFloat(c[pi] || "0") });
          }
        }
      }
    }

    // 매도 후보 파싱 (rebalancer JSON)
    let sellStocks = [];
    const rebalResp = await fetch(rebalUrl);
    if (rebalResp.ok) {
      const rebal = await rebalResp.json();
      sellStocks = (rebal.sell || []).map((s) => ({
        symbol: s.symbol, qty: s.qty, current: s.current,
      }));
    }

    if (buyStocks.length === 0 && sellStocks.length === 0) {
      return "\ud83d\udced *\ucd94\ucc9c \uc885\ubaa9 \uc5c6\uc74c*\n\n\uc624\ub298 \ub9ac\ud3ec\ud2b8\uc5d0\uc11c \ub9e4\uc218/\ub9e4\ub3c4 \ucd94\ucc9c\uc774 \uc5c6\uc5c8\uc2b5\ub2c8\ub2e4.";
    }

    let msg = "\ud83c\udfaf *\uc2b9\uc778 \ucc98\ub9ac \uacb0\uacfc*\n\n";
    let buyMsg = "";
    let sellMsg = "";

    // \ub9e4\ub3c4 \uba3c\uc800 \uc2e4\ud589 (\uc608\uc218\uae08 \ud655\ubcf4)
    if (sellStocks.length > 0) {
      sellMsg += "\ud83d\udd34 *\ub9e4\ub3c4:*\n";
      for (const s of sellStocks) {
        const ok = await sellOrder(env, s.symbol, s.qty, s.current);
        sellMsg += ok
          ? `  \u2705 ${s.symbol} ${s.qty}\uc8fc \u00d7 $${s.current.toFixed(2)} \ub9e4\ub3c4 \uc8fc\ubb38 \uc811\uc218\n`
          : `  \u274c ${s.symbol} \ub9e4\ub3c4 \uc2e4\ud328\n`;
      }
      sellMsg += "\n";
    }

    // \ub9e4\uc218 \uc2e4\ud589
    if (buyStocks.length > 0) {
      const holdings = await getBalance(env);
      const heldSymbols = (holdings || []).filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0).map(h => h.ovrs_pdno);
      buyStocks = buyStocks.filter(s => !heldSymbols.includes(s.symbol));

      if (buyStocks.length === 0) {
        buyMsg += "\u2139\ufe0f \ubaa8\ub4e0 \ucd94\ucc9c \uc885\ubaa9\uc744 \uc774\ubbf8 \ubcf4\uc720 \uc911\uc785\ub2c8\ub2e4.\n\n";
      } else {
        const bp = await getBuyingPower(env);
        const cash = parseFloat(bp?.ord_psbl_frcr_amt || "0");
        const perStock = Math.floor(cash * 0.05 * 100) / 100;

        if (perStock < 10) {
          buyMsg += "\u26a0\ufe0f \ub9e4\uc218 \ubd88\uac00: \uc608\uc218\uae08 \ubd80\uc871 (\uc885\ubaa9\ub2f9 $" + perStock.toFixed(2) + ")\n\n";
        } else {
          buyMsg += "\ud83d\udfe2 *\ub9e4\uc218:*\n";
          buyMsg += `  \ud83d\udcb0 \uc885\ubaa9\ub2f9 \ud22c\uc790\uae08: *$${perStock.toFixed(2)}* (\uc608\uc218\uae08 5%)\n\n`;
          for (const s of buyStocks) {
            if (s.price <= 0) continue;
            let qty = Math.floor(perStock / s.price);

            if (qty <= 0) {
              buyMsg += `  \u26a0\ufe0f ${s.symbol}: \ub2e8\uac00 $${s.price.toFixed(2)} > \ud22c\uc790\uae08\n`;
              continue;
            }
            const ok = await buyOrder(env, s.symbol, qty, s.price.toFixed(2));
            buyMsg += ok
              ? `  \u2705 ${s.symbol} ${qty}\uc8fc \u00d7 $${s.price.toFixed(2)} \ub9e4\uc218 \uc8fc\ubb38 \uc811\uc218\n`
              : `  \u274c ${s.symbol} \ub9e4\uc218 \uc2e4\ud328\n`;
          }
          buyMsg += "\n";
        }
      }
    }

    // 표시: 매수 먼저, 매도 나중에
    msg += buyMsg + sellMsg;

    // 주문한 종목 목록 수집 (체결 확인용)
    const orderedSymbols = [
      ...sellStocks.map(s => s.symbol),
      ...buyStocks.map(s => s.symbol),
    ];

    return { msg, orderedSymbols };
  } catch (e) {
    return "\u26a0\ufe0f \uc2b9\uc778 \ucc98\ub9ac \uc5d0\ub7ec: " + e.message;
  }
}

async function handleApproval(env) {
  if (isMarketOpen()) {
    // Market open -> execute immediately
    const result = await executeApproval(env);
    if (typeof result === "string") return result;
    // KV에 체결 확인 대상 저장 → 5분 간격 cron이 확인
    await saveFillCheckToKV(env, result.orderedSymbols);
    return result.msg;
  } else {
    // Market closed -> save reservation to KV
    if (env.KV) {
      await env.KV.put("pending_approval", JSON.stringify({
        type: "approval",
        requested_at: new Date().toISOString(),
      }));
      return "✅ *승인 예약 완료!*\n\n" +
        "🕒 미국 장 개장(23:30 KST) 시 자동 매수/매도를 실행합니다.\n" +
        "📥 주문 접수 + 체결 확인 알림을 별도로 보내드리겠습니다, 대표님.\n\n" +
        "취소하려면 \"예약취소\" 라고 입력해 주세요.";
    } else {
      return "⚠️ KV 저장소가 연결되지 않았습니다.";
    }
  }
}

async function handleReject(env) {
  return "🛡️ *반려 처리 완료*\n\n현재 포트폴리오를 유지합니다, 대표님.";
}

// === Menu Handlers ===
async function handleTotalReturn(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0) {
      const bp = await getBuyingPower(env);
      const usd = bp ? bp.ord_psbl_frcr_amt : "조회 실패";
      return "\ud83d\udcca *\uc804\uccb4 \uc218\uc775\ub960*\n\n\ud83d\udced \ud604\uc7ac \ubcf4\uc720 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.\n\ud83d\udcb0 \uc608\uc218\uae08: *$" + usd + "*\n\n\ud604\uae08 100% \uc0c1\ud0dc\uc785\ub2c8\ub2e4, \ub300\ud45c\ub2d8! \ud83d\udee1\ufe0f";
    }

    let totalInvested = 0, totalEval = 0, totalPnl = 0;
    for (const h of holdings) {
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      if (qty <= 0) continue;
      const buyAvg = parseFloat(h.pchs_avg_pric || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const pnl = parseFloat(h.frcr_evlu_pfls_amt || "0");
      totalInvested += buyAvg * qty;
      totalEval += cur * qty;
      totalPnl += pnl;
    }

    const rate = totalInvested > 0 ? (totalPnl / totalInvested * 100) : 0;
    const emoji = totalPnl >= 0 ? "\ud83d\ude80" : "\ud83d\udcc9";
    const activeCount = holdings.filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0).length;

    return "\ud83d\udcca *\uc804\uccb4 \uc218\uc775\ub960*\n\n\ud83d\udcb0 \ucd1d \ud3c9\uac00\uae08\uc561: *$" + totalEval.toFixed(2) + "*\n\ud83d\udcb5 \ud22c\uc790 \uc6d0\uae08: $" + totalInvested.toFixed(2) + "\n" + emoji + " \ub204\uc801 \uc218\uc775\ub960: *" + (rate >= 0 ? "+" : "") + rate.toFixed(1) + "%* (" + (totalPnl >= 0 ? "+" : "") + totalPnl.toFixed(2) + ")\n\ud83d\udccb \ubcf4\uc720 \uc885\ubaa9: " + activeCount + "\uac1c";
  } catch (e) {
    return "\u26a0\ufe0f \uc870\ud68c \uc5d0\ub7ec: " + e.message;
  }
}

async function handleStockReturn(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0)
      return "\ud83d\udcc8 *\uc885\ubaa9\ubcc4 \uc218\uc775\ub960*\n\n\ud83d\udced \ubcf4\uc720 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4, \ub300\ud45c\ub2d8.";

    let msg = "\ud83d\udcc8 *\uc885\ubaa9\ubcc4 \uc218\uc775\ub960*\n\n";
    const active = holdings.filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0);
    
    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const buyAvg = parseFloat(h.pchs_avg_pric || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const pnlRt = parseFloat(h.evlu_pfls_rt || "0");
      const pnl = parseFloat(h.frcr_evlu_pfls_amt || "0");
      const emoji = pnl >= 0 ? "\ud83d\udfe2" : "\ud83d\udd34";
      msg += emoji + " *" + sym + "* (" + (pnlRt >= 0 ? "+" : "") + pnlRt.toFixed(1) + "%)\n   " + qty + "\uc8fc | \ub9e4\uc785 $" + buyAvg.toFixed(2) + " \u2192 \ud604\uc7ac $" + cur.toFixed(2) + "\n   \uc190\uc775: " + (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "\n\n";
    }

    if (active.length > 0) {
      const best = active.reduce((a, b) => parseFloat(a.evlu_pfls_rt || "0") > parseFloat(b.evlu_pfls_rt || "0") ? a : b);
      msg += "\ud83c\udfc6 \ud6a8\uc790 \uc885\ubaa9: *" + (best.ovrs_pdno || "?") + "*";
    }
    return msg;
  } catch (e) {
    return "\u26a0\ufe0f \uc870\ud68c \uc5d0\ub7ec: " + e.message;
  }
}

async function handleDeposit(env) {
  try {
    const bp = await getBuyingPower(env);
    if (!bp) return "\u26a0\ufe0f \uc608\uc218\uae08 \uc870\ud68c\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.";

    const usd = bp.ord_psbl_frcr_amt || "0";
    const holdings = await getBalance(env);
    
    let cashRatio = 100;
    if (holdings && holdings.length > 0) {
      const totalEval = holdings.reduce((sum, h) => {
        const qty = parseInt(h.ovrs_cblc_qty || "0");
        return qty > 0 ? sum + parseFloat(h.now_pric2 || "0") * qty : sum;
      }, 0);
      const totalAsset = totalEval + parseFloat(usd);
      cashRatio = totalAsset > 0 ? (parseFloat(usd) / totalAsset * 100) : 100;
    }

    let advice = "\ud83d\udee1\ufe0f \ub300\ubd80\ubd84 \ud604\uae08 \ubcf4\uc720 \uc911\uc785\ub2c8\ub2e4. \uc548\uc804\ud55c \uc0c1\ud0dc\uc785\ub2c8\ub2e4!";
    if (cashRatio < 50) advice = "\ud83d\udcc8 \ud22c\uc790 \ube44\uc911\uc774 \ub192\uc2b5\ub2c8\ub2e4. \uc2dc\uc7a5 \ubcc0\ub3d9\uc5d0 \uc720\uc758\ud574 \uc8fc\uc138\uc694.";
    else if (cashRatio < 80) advice = "\u2696\ufe0f \uc801\uc808\ud55c \ud604\uae08 \ube44\uc911\uc744 \uc720\uc9c0\ud558\uace0 \uc788\uc2b5\ub2c8\ub2e4.";

    return "\ud83d\udcb5 *\uc608\uc218\uae08 \ud604\ud669*\n\n\ud83d\udcb0 \uc989\uc2dc \ub9e4\uc218 \uac00\ub2a5: *$" + usd + "*\n\ud83d\udcca \ud604\uae08 \ube44\uc911: " + cashRatio.toFixed(0) + "%\n\n" + advice;
  } catch (e) {
    return "\u26a0\ufe0f \uc870\ud68c \uc5d0\ub7ec: " + e.message;
  }
}

async function handleBalance(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0)
      return "\ud83d\udcb0 *\uc2e4\uc2dc\uac04 \uc794\uace0*\n\n\ud83d\udced \ubcf4\uc720 \uc885\ubaa9 \uc5c6\uc74c. \ud604\uae08 100% \uc0c1\ud0dc\uc785\ub2c8\ub2e4.";

    const active = holdings.filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0);
    let totalEval = 0;
    let msg = "\ud83d\udcb0 *\uc2e4\uc2dc\uac04 \uc794\uace0*\n\n\ud83d\udccb \ud604\uc7ac *" + active.length + "\uc885\ubaa9* \ubcf4\uc720 \uc911:\n";

    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const evalAmt = cur * qty;
      totalEval += evalAmt;
      msg += "  \u2022 *" + sym + "*: " + qty + "\uc8fc \u00d7 $" + cur.toFixed(2) + " = $" + evalAmt.toFixed(2) + "\n";
    }
    msg += "\n\ud83d\udcc8 \ucd1d \ud3c9\uac00\uc561: *$" + totalEval.toFixed(2) + "*";
    return msg;
  } catch (e) {
    return "\u26a0\ufe0f \uc870\ud68c \uc5d0\ub7ec: " + e.message;
  }
}

async function handleTodayScan(env) {
  try {
    const ts = Date.now();
    const url = `https://raw.githubusercontent.com/abraxass0511-lab/Alpha-Investment-Agent/main/output_reports/metadata.json?t=${ts}`;
    const r = await fetch(url);
    if (!r.ok) return "\ud83d\udd0d *\uc624\ub298\uc790 \uc2a4\uce94*\n\n\u274c \uc544\uc9c1 \uc624\ub298 \uc2a4\uce94\uc774 \uc2e4\ud589\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.";
    
    const meta = await r.json();
    const scanTime = (meta.timestamp || "N/A").substring(0, 16);
    const step5 = meta.step5 || 0;

    let msg = "\ud83d\udd0d *\uc624\ub298\uc790 \uc2a4\uce94 \uacb0\uacfc*\n\n\ud83d\udcc5 \uc2a4\uce94 \uc2dc\uac01: " + scanTime + "\n\n";
    msg += "`1+2\ub2e8\uacc4` \uccb4\uae09+\ub0b4\uc2e4 : " + (meta.total || 503) + " \u2192 *" + (meta.step12 || meta.step1 || 0) + "\uac74*\n";
    msg += "`3\ub2e8\uacc4` \uc5d0\ub108\uc9c0 : \u2192 *" + (meta.step3 || 0) + "\uac74*\n";
    msg += "`4\ub2e8\uacc4` \uc131\uc7a5   : \u2192 *" + (meta.step4 || 0) + "\uac74*\n";
    msg += "`5\ub2e8\uacc4` \ubaa8\uba58\ud140 : \u2192 *" + step5 + "\uac74*\n\n";
    msg += step5 > 0
      ? "\ud83d\udd25 \ucd5c\uc885 \ud1b5\uacfc \uc885\ubaa9 *" + step5 + "\uac1c*! \ub9ac\ud3ec\ud2b8\ub97c \ud655\uc778\ud574 \uc8fc\uc138\uc694."
      : "\ud83d\udee1\ufe0f \uc624\ub298\uc740 \uae30\uc900 \ucda9\uc871 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \ud604\uae08 \ubcf4\uc720 \uad8c\uace0!";
    return msg;
  } catch (e) {
    return "\u26a0\ufe0f \uc870\ud68c \uc5d0\ub7ec: " + e.message;
  }
}

async function handleEmergencySell(env) {
  return (
    "\ud83d\uded1 *\uae34\uae09 \uc804\ub7c9 \ub9e4\ub3c4 \ud655\uc778*\n\n" +
    "\u26a0\ufe0f \ubaa8\ub4e0 \ubcf4\uc720 \uc885\ubaa9\uc744 \ub9e4\ub3c4\ud569\ub2c8\ub2e4.\n" +
    "\u2022 \uc7a5 \uc5f4\ub9bc: \uc989\uc2dc \uc2e4\ud589\n" +
    "\u2022 \uc7a5 \ub2eb\ud798: \uac1c\uc7a5(23:30) \uc608\uc57d\n\n" +
    "\uc815\ub9d0 \uc2e4\ud589\ud558\uc2dc\uaca0\uc2b5\ub2c8\uae4c?\n" +
    "\u2192 \"\uc804\ub7c9\ub9e4\ub3c4\" \ub77c\uace0 \uc785\ub825\ud574 \uc8fc\uc138\uc694.\n" +
    "\u2192 \uc608\uc57d \ud6c4 \ucde8\uc18c: \"\uc608\uc57d\ucde8\uc18c\" \uc785\ub825 (23:30 \uc804\uae4c\uc9c0)"
  );
}

const US_HOLIDAYS = [
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
  "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
  "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
  "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"
];

// US Eastern Time 시간 반환 (EDT/EST 자동 감지)
function getETHour() {
  const now = new Date();
  // Intl API로 정확한 US Eastern 시간 추출
  try {
    const etStr = now.toLocaleString("en-US", { timeZone: "America/New_York", hour12: false, hour: "2-digit" });
    return parseInt(etStr);
  } catch {
    // Intl 미지원 환경 폴백: 3월 둘째 일요일~11월 첫째 일요일 = EDT(UTC-4), 나머지 EST(UTC-5)
    const utcMonth = now.getUTCMonth(); // 0-indexed
    const isDST = utcMonth >= 2 && utcMonth <= 10; // 3월~11월 (대략적)
    const offset = isDST ? 4 : 5;
    return (now.getUTCHours() - offset + 24) % 24;
  }
}

function isTradingDay(dateObj) {
  const utcDay = dateObj.getUTCDay();
  // 0: 일요일, 6: 토요일
  if (utcDay === 0 || utcDay === 6) return false;
  
  // yyyy-mm-dd 포맷으로 공휴일 검사
  const ymd = dateObj.toISOString().split("T")[0];
  if (US_HOLIDAYS.includes(ymd)) return false;

  return true;
}

function isMarketOpen() {
  const now = new Date();
  
  // 주말이거나 공휴일이면 어떤 시간대든 무조건 장 닫힘 (예약 처리)
  if (!isTradingDay(now)) return false;

  // US Eastern Time (UTC-4 EDT / UTC-5 EST)
  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();
  const utcMin = utcH * 60 + utcM;
  // EDT: 9:30-16:00 = UTC 13:30-20:00
  // EST: 9:30-16:00 = UTC 14:30-21:00
  // Use broader range to cover both
  return utcMin >= 13 * 60 + 30 && utcMin < 21 * 60;
}

async function handleSellConfirm(env) {
  if (isMarketOpen()) {
    // Market open -> sell immediately
    return await executeEmergencySell(env);
  } else {
    // Market closed -> save reservation to KV
    if (env.KV) {
      await env.KV.put("pending_sell", JSON.stringify({
        type: "sell_all",
        requested_at: new Date().toISOString(),
      }));
      return "\u2705 *\ub9e4\ub3c4 \uc608\uc57d \uc644\ub8cc!*\n\n" +
        "\ud83d\udd52 \ubbf8\uad6d \uc7a5 \uac1c\uc7a5(23:30 KST) \uc2dc \uc790\ub3d9 \uc2e4\ud589\ud569\ub2c8\ub2e4.\n" +
        "\ud83d\udce9 \uacb0\uacfc\ub294 \ud154\ub808\uadf8\ub7a8\uc73c\ub85c \uc54c\ub824\ub4dc\ub9ac\uaca0\uc2b5\ub2c8\ub2e4, \ub300\ud45c\ub2d8.\n\n" +
        "\ucde8\uc18c\ud558\ub824\uba74 \"\uc608\uc57d\ucde8\uc18c\" \ub77c\uace0 \uc785\ub825\ud574 \uc8fc\uc138\uc694.";
    } else {
      return "\u26a0\ufe0f KV \uc800\uc7a5\uc18c\uac00 \uc5f0\uacb0\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.";
    }
  }
}

async function handleCancelReservation(env) {
  if (env.KV) {
    let cancelled = false;
    const p1 = await env.KV.get("pending_sell");
    if (p1) { await env.KV.delete("pending_sell"); cancelled = true; }
    
    const p2 = await env.KV.get("pending_approval");
    if (p2) { await env.KV.delete("pending_approval"); cancelled = true; }
    
    if (cancelled) {
      return "❌ *예약이 정상적으로 취소되었습니다.*\n\n🛡️ 예약된 주문이 제거되었으며, 현재 포트폴리오를 유지합니다, 대표님.";
    }
  }
  return "⚠️ 취소할 예약(승인 대기 건 또는 매도 대기 건)이 없습니다.";
}

async function executeEmergencySell(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0)
      return "\ud83d\udced \ubcf4\uc720 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc774\ubbf8 \ud604\uae08 100% \uc0c1\ud0dc\uc785\ub2c8\ub2e4.";

    const active = holdings.filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0);
    if (active.length === 0) return "\ud83d\udced \ubcf4\uc720 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.";

    let msg = "\ud83d\uded1 *[\uc804\ub7c9 \ub9e4\ub3c4 \uc2e4\ud589]*\n\n";
    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const sellPrice = (cur * 0.995).toFixed(2);

      const success = await sellOrder(env, sym, qty, sellPrice);
      const status = success ? "\u2705 \uc644\ub8cc" : "\u274c \uc2e4\ud328";
      msg += "  " + status + " *" + sym + "* " + qty + "\uc8fc \u00d7 $" + sellPrice + "\n";
    }
    msg += "\n\ud83d\udee1\ufe0f \ub9e4\ub3c4 \ucc98\ub9ac\uac00 \uc644\ub8cc\ub418\uc5c8\uc2b5\ub2c8\ub2e4, \ub300\ud45c\ub2d8.";
    return msg;
  } catch (e) {
    return "\u26a0\ufe0f \ub9e4\ub3c4 \uc5d0\ub7ec: " + e.message;
  }
}

async function handleAiChat(env, question) {
  try {
    if (!env.GEMINI_API_KEY) return "\u26a0\ufe0f AI \uc5d4\uc9c4\uc774 \uc5f0\uacb0\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.";

    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${env.GEMINI_API_KEY}`;
    
    let ctx = "";
    try {
      const holdings = await getBalance(env);
      if (holdings && holdings.length > 0) {
        ctx += "### Portfolio\n";
        for (const h of holdings) {
          const qty = parseInt(h.ovrs_cblc_qty || "0");
          if (qty <= 0) continue;
          ctx += "- " + h.ovrs_pdno + ": " + qty + " shares, buy $" + parseFloat(h.pchs_avg_pric||"0").toFixed(2) + ", now $" + parseFloat(h.now_pric2||"0").toFixed(2) + ", return " + parseFloat(h.evlu_pfls_rt||"0").toFixed(1) + "%\n";
        }
      }
    } catch {}

    const systemPrompt = "\ub108\ub294 '\uc5d0\uc774\uc804\ud2b8 \uc54c\ud30c'\uc57c. \ubbf8\uad6d \uc8fc\uc2dd \ud22c\uc790\ub97c \uc804\ub2f4\ud558\ub294 AI \ube44\uc11c.\n\ud56d\uc0c1 \"\ub300\ud45c\ub2d8\"\uc774\ub77c\uace0 \ud638\uce6d. \uac04\uacb0\ud558\uace0 \ud575\uc2ec \uc704\uc8fc. \ub370\uc774\ud130 \uae30\ubc18 \ub2f5\ubcc0\ub9cc. \ud154\ub808\uadf8\ub7a8 Markdown \ud615\uc2dd. \ub2f5\ubcc0 300\uc790 \uc774\ub0b4. \uc774\ubaa8\uc9c0 \uc0ac\uc6a9.\n" + ctx;

    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: systemPrompt }] },
        contents: [{ parts: [{ text: question }] }],
        generationConfig: { temperature: 0.7, maxOutputTokens: 500 },
      }),
    });

    if (r.status === 429) return "\u26a0\ufe0f AI \ubb34\ub8cc \uc81c\uacf5\ub7c9 \ucd08\uacfc. \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574 \uc8fc\uc138\uc694.";
    if (!r.ok) return "\u26a0\ufe0f AI \uc751\ub2f5 \uc5d0\ub7ec (HTTP " + r.status + ")";

    const data = await r.json();
    return data.candidates[0].content.parts[0].text.trim();
  } catch (e) {
    return "\u26a0\ufe0f AI \uc5d0\ub7ec: " + e.message;
  }
}

// === Main Update Handler ===
const TEXT_HANDLERS = {
  "\ud83d\udcca \uc804\uccb4 \uc218\uc775\ub960": handleTotalReturn,
  "\ud83d\udcc8 \uc885\ubaa9\ubcc4 \uc218\uc775\ub960": handleStockReturn,
  "\ud83d\udcb5 \uc608\uc218\uae08 \ud604\ud669": handleDeposit,
  "\ud83d\udcb0 \uc2e4\uc2dc\uac04 \uc794\uace0": handleBalance,
  "\ud83d\udd0d \uc624\ub298\uc790 \uc2a4\uce94": handleTodayScan,
  "\ud83d\uded1 \uae34\uae09 \uc804\ub7c9 \ub9e4\ub3c4": handleEmergencySell,
};

async function handleUpdate(update, env) {
  if (!update.message) return;

  const msg = update.message;
  const text = (msg.text || "").trim();
  const fromId = String(msg.from?.id || "");

  if (fromId !== String(env.TELEGRAM_CHAT_ID)) return;

  if (["/menu", "/start"].includes(text.toLowerCase()) || text === "\uba54\ub274") {
    await sendMessage(env, "\ud83e\udd16 *\uc54c\ud30c \uc5d0\uc774\uc804\ud2b8 \uba54\ub274*\n\n\ud558\ub2e8 \ubc84\ud2bc\uc744 \ub20c\ub7ec\uc8fc\uc138\uc694, \ub300\ud45c\ub2d8!", REPLY_KEYBOARD);
    return;
  }

  // Sell confirm
  if (text === "\uc804\ub7c9\ub9e4\ub3c4") {
    const response = await handleSellConfirm(env);
    await sendMessage(env, response, REPLY_KEYBOARD);
    return;
  }

  // Cancel reservation
  if (text === "\uc608\uc57d\ucde8\uc18c") {
    const response = await handleCancelReservation(env);
    await sendMessage(env, response, REPLY_KEYBOARD);
    return;
  }

  if (TEXT_HANDLERS[text]) {
    const response = await TEXT_HANDLERS[text](env);
    await sendMessage(env, response, REPLY_KEYBOARD);
    return;
  }

  // Retry scan
  if (text === "\uc2dc\ub3c4") {
    if (!env.GITHUB_PAT) {
      await sendMessage(env, "\u26a0\ufe0f GitHub \uc5f0\ub3d9\uc774 \uc124\uc815\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.", REPLY_KEYBOARD);
      return;
    }
    try {
      const r = await fetch("https://api.github.com/repos/abraxass0511-lab/Alpha-Investment-Agent/actions/workflows/alpha_daily.yml/dispatches", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GITHUB_PAT}`,
          "Accept": "application/vnd.github+json",
          "User-Agent": "Alpha-Bot",
        },
        body: JSON.stringify({ ref: "main" }),
      });
      if (r.ok || r.status === 204) {
        await sendMessage(env, "\ud83d\udd04 *\uc2a4\uce94 \uc7ac\uc2dc\ub3c4 \uc2dc\uc791!*\n\n\uc57d 20~30\ubd84 \ud6c4 \uacb0\uacfc\ub97c \uc54c\ub824\ub4dc\ub9ac\uaca0\uc2b5\ub2c8\ub2e4, \ub300\ud45c\ub2d8.", REPLY_KEYBOARD);
      } else {
        const body = await r.text().catch(() => "");
        await sendMessage(env, "\u26a0\ufe0f *GitHub \uc11c\ubc84 \ubb38\uc81c*\n\n\uc2a4\uce94 \uc694\uccad\uc744 GitHub\uc5d0 \uc804\ub2ec\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.\nHTTP " + r.status + "\n\n\uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.", REPLY_KEYBOARD);
      }
    } catch (e) {
      await sendMessage(env, "\u26a0\ufe0f *GitHub \uc811\uc18d \uc2e4\ud328*\n\nGitHub \uc11c\ubc84\uc5d0 \uc5f0\uacb0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.\n\uc624\ub958: " + (e.message || "Unknown") + "\n\n\uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.", REPLY_KEYBOARD);
    }
    return;
  }

  // Skip today
  if (text === "\uc885\ub8cc") {
    await sendMessage(env, "\u2705 *\uc624\ub298 \uc2a4\uce94\uc744 \uac74\ub108\ub6f5\ub2c8\ub2e4.*\n\n\ub0b4\uc77c \uc815\uc0c1 \uc2e4\ud589\ub429\ub2c8\ub2e4, \ub300\ud45c\ub2d8.", REPLY_KEYBOARD);
    return;
  }

  if (text === "\uc2b9\uc778") {
    const response = await handleApproval(env);
    await sendMessage(env, response, REPLY_KEYBOARD);
    return;
  }

  if (text === "\\ubc18\\ub824") {
    const response = await handleReject(env);
    await sendMessage(env, response, REPLY_KEYBOARD);
    return;
  }

  const response = await handleAiChat(env, text);
  await sendMessage(env, response, REPLY_KEYBOARD);
}
