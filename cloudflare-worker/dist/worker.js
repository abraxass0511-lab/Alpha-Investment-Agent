var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// worker.js
var worker_default = {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/debug") {
      try {
        const results = {};
        const token = await getKisToken(env);
        results.token = token ? "OK" : "FAIL";
        if (token) {
          const balUrl = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance`;
          const balParams = new URLSearchParams({
            CANO: env.KIS_CANO,
            ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
            OVRS_EXCG_CD: "NASD",
            TR_CRCY_CD: "USD",
            CTX_AREA_FK200: "",
            CTX_AREA_NK200: ""
          });
          const balR = await fetch(`${balUrl}?${balParams}`, {
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              appkey: env.KIS_APP_KEY,
              appsecret: env.KIS_SECRET_KEY,
              "tr_id": "VTTS3012R"
            }
          });
          results.balance_raw = await balR.json();
          const bpUrl = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-psamount`;
          const bpParams = new URLSearchParams({
            CANO: env.KIS_CANO,
            ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
            OVRS_EXCG_CD: "NASD",
            OVRS_ORD_UNPR: "0",
            ITEM_CD: "AAPL"
          });
          const bpR = await fetch(`${bpUrl}?${bpParams}`, {
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              appkey: env.KIS_APP_KEY,
              appsecret: env.KIS_SECRET_KEY,
              "tr_id": "VTTS3007R"
            }
          });
          results.buying_power_raw = await bpR.json();
          if (env.KV) {
            results.pending_sell = await env.KV.get("pending_sell");
          }
        }
        return new Response(JSON.stringify(results, null, 2), {
          headers: { "Content-Type": "application/json" }
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          headers: { "Content-Type": "application/json" }
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
  // Cron Trigger: market open (23:30 KST)
  async scheduled(event, env, ctx) {
    try {
      if (!isTradingDay(/* @__PURE__ */ new Date())) return;
      const sellPend = await env.KV.get("pending_sell");
      if (sellPend) {
        const data = JSON.parse(sellPend);
        if (data.type === "sell_all") {
          const result = await executeEmergencySell(env);
          await sendMessage(env, "\u23F0 *[\uC608\uC57D \uB9E4\uB3C4 \uC2E4\uD589]*\n\n" + result, REPLY_KEYBOARD);
        }
        await env.KV.delete("pending_sell");
      }
      const appPend = await env.KV.get("pending_approval");
      if (appPend) {
        const data = JSON.parse(appPend);
        if (data.type === "approval") {
          const result = await executeApproval(env);
          await sendMessage(env, "\u23F0 *[\uC608\uC57D \uC2B9\uC778(\uB9E4\uC218/\uB9E4\uB3C4) \uC790\uB3D9 \uC9D1\uD589]*\n\n" + result, REPLY_KEYBOARD);
        }
        await env.KV.delete("pending_approval");
      }
    } catch (e) {
      await sendMessage(env, "\u26A0\uFE0F \uC608\uC57D \uC2E4\uD589 \uC911 \uC5D0\uB7EC: " + e.message, REPLY_KEYBOARD);
    }
  }
};
async function sendMessage(env, text, replyMarkup) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = {
    chat_id: env.TELEGRAM_CHAT_ID,
    text: text.substring(0, 4096),
    parse_mode: "Markdown"
  };
  if (replyMarkup) body.reply_markup = replyMarkup;
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}
__name(sendMessage, "sendMessage");
var REPLY_KEYBOARD = {
  keyboard: [
    ["\u{1F4CA} \uC804\uCCB4 \uC218\uC775\uB960", "\u{1F4C8} \uC885\uBAA9\uBCC4 \uC218\uC775\uB960"],
    ["\u{1F4B5} \uC608\uC218\uAE08 \uD604\uD669", "\u{1F4B0} \uC2E4\uC2DC\uAC04 \uC794\uACE0"],
    ["\u{1F50D} \uC624\uB298\uC790 \uC2A4\uCE94", "\u{1F6D1} \uAE34\uAE09 \uC804\uB7C9 \uB9E4\uB3C4"]
  ],
  resize_keyboard: true,
  is_persistent: true
};
var _cachedToken = null;
var _tokenIssuedAt = 0;
var TOKEN_TTL = 6 * 3600 * 1e3 - 5 * 60 * 1e3;
async function getKisToken(env, forceRefresh = false) {
  const now = Date.now();
  if (!forceRefresh && _cachedToken && now - _tokenIssuedAt < TOKEN_TTL) {
    return _cachedToken;
  }
  const url = `${env.KIS_BASE_URL}/oauth2/tokenP`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "client_credentials",
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY
    })
  });
  const data = await r.json();
  _cachedToken = data.access_token;
  _tokenIssuedAt = now;
  return _cachedToken;
}
__name(getKisToken, "getKisToken");
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
    CTX_AREA_NK200: ""
  });
  const r = await fetch(`${url}?${params}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTS3012R"
    }
  });
  const data = await r.json();
  if (data.rt_cd === "0") return data.output1 || [];
  if (!_retry) {
    _cachedToken = null;
    _tokenIssuedAt = 0;
    return getBalance(env, true);
  }
  return null;
}
__name(getBalance, "getBalance");
async function getBuyingPower(env, _retry = false) {
  const token = await getKisToken(env);
  if (!token) return null;
  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-psamount`;
  const params = new URLSearchParams({
    CANO: env.KIS_CANO,
    ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
    OVRS_EXCG_CD: "NASD",
    OVRS_ORD_UNPR: "0",
    ITEM_CD: "AAPL"
  });
  const r = await fetch(`${url}?${params}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      appkey: env.KIS_APP_KEY,
      appsecret: env.KIS_SECRET_KEY,
      "tr_id": "VTTS3007R"
    }
  });
  const data = await r.json();
  if (data.rt_cd === "0") {
    const output = data.output || {};
    return {
      ord_psbl_frcr_amt: output.ord_psbl_frcr_amt || output.ovrs_ord_psbl_amt || "0"
    };
  }
  if (!_retry) {
    _cachedToken = null;
    _tokenIssuedAt = 0;
    return getBuyingPower(env, true);
  }
  return null;
}
__name(getBuyingPower, "getBuyingPower");
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
      "tr_id": "VTTT1006U"
    },
    body: JSON.stringify({
      CANO: env.KIS_CANO,
      ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
      OVRS_EXCG_CD: "NASD",
      PDNO: symbol,
      ORD_QTY: String(qty),
      OVRS_ORD_UNPR: String(price),
      ORD_SVR_DVSN_CD: "0",
      ORD_DVSN: "00"
    })
  });
  const data = await r.json();
  return data.rt_cd === "0";
}
__name(sellOrder, "sellOrder");
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
      "tr_id": "VTTT1002U"
    },
    body: JSON.stringify({
      CANO: env.KIS_CANO,
      ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
      OVRS_EXCG_CD: "NASD",
      PDNO: symbol,
      ORD_QTY: String(qty),
      OVRS_ORD_UNPR: String(price),
      ORD_SVR_DVSN_CD: "0",
      ORD_DVSN: "00"
    })
  });
  const data = await r.json();
  return data.rt_cd === "0";
}
__name(buyOrder, "buyOrder");
async function executeApproval(env) {
  try {
    const ts = Date.now();
    const picksUrl = `https://raw.githubusercontent.com/abraxass0511-lab/Alpha-Investment-Agent/main/output_reports/final_picks_latest.csv?t=${ts}`;
    const rebalUrl = `https://raw.githubusercontent.com/abraxass0511-lab/Alpha-Investment-Agent/main/output_reports/rebalance_recommendations.json?t=${ts}`;
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
    let sellStocks = [];
    const rebalResp = await fetch(rebalUrl);
    if (rebalResp.ok) {
      const rebal = await rebalResp.json();
      sellStocks = (rebal.sell || []).map((s) => ({
        symbol: s.symbol,
        qty: s.qty,
        current: s.current
      }));
    }
    if (buyStocks.length === 0 && sellStocks.length === 0) {
      return "\u{1F4ED} *\uCD94\uCC9C \uC885\uBAA9 \uC5C6\uC74C*\n\n\uC624\uB298 \uB9AC\uD3EC\uD2B8\uC5D0\uC11C \uB9E4\uC218/\uB9E4\uB3C4 \uCD94\uCC9C\uC774 \uC5C6\uC5C8\uC2B5\uB2C8\uB2E4.";
    }
    let msg = "\u{1F3AF} *\uC2B9\uC778 \uCC98\uB9AC \uACB0\uACFC*\n\n";
    let buyMsg = "";
    let sellMsg = "";
    if (sellStocks.length > 0) {
      sellMsg += "\u{1F534} *\uB9E4\uB3C4:*\n";
      for (const s of sellStocks) {
        const ok = await sellOrder(env, s.symbol, s.qty, s.current);
        sellMsg += ok ? `  \u2705 ${s.symbol} ${s.qty}\uC8FC \xD7 $${s.current.toFixed(2)} \uB9E4\uB3C4 \uC644\uB8CC
` : `  \u274C ${s.symbol} \uB9E4\uB3C4 \uC2E4\uD328
`;
      }
      sellMsg += "\n";
    }
    if (buyStocks.length > 0) {
      const holdings = await getBalance(env);
      const heldSymbols = (holdings || []).filter((h) => parseInt(h.ovrs_cblc_qty || "0") > 0).map((h) => h.ovrs_pdno);
      buyStocks = buyStocks.filter((s) => !heldSymbols.includes(s.symbol));
      if (buyStocks.length === 0) {
        buyMsg += "\u2139\uFE0F \uBAA8\uB4E0 \uCD94\uCC9C \uC885\uBAA9\uC744 \uC774\uBBF8 \uBCF4\uC720 \uC911\uC785\uB2C8\uB2E4.\n\n";
      } else {
        const bp = await getBuyingPower(env);
        const cash = parseFloat(bp?.ord_psbl_frcr_amt || "0");
        const perStock = Math.floor(cash * 0.05 * 100) / 100;
        if (perStock < 10) {
          buyMsg += "\u26A0\uFE0F \uB9E4\uC218 \uBD88\uAC00: \uC608\uC218\uAE08 \uBD80\uC871 (\uC885\uBAA9\uB2F9 $" + perStock.toFixed(2) + ")\n\n";
        } else {
          buyMsg += "\u{1F7E2} *\uB9E4\uC218:*\n";
          buyMsg += `  \u{1F4B0} \uC885\uBAA9\uB2F9 \uD22C\uC790\uAE08: *$${perStock.toFixed(2)}* (\uC608\uC218\uAE08 5%)

`;
          for (const s of buyStocks) {
            if (s.price <= 0) continue;
            let qty = Math.floor(perStock / s.price);
            if (s.symbol === "GOOGL") {
              qty = 1;
            }
            if (qty <= 0) {
              buyMsg += `  \u26A0\uFE0F ${s.symbol}: \uB2E8\uAC00 $${s.price.toFixed(2)} > \uD22C\uC790\uAE08
`;
              continue;
            }
            const ok = await buyOrder(env, s.symbol, qty, s.price.toFixed(2));
            buyMsg += ok ? `  \u2705 ${s.symbol} ${qty}\uC8FC \xD7 $${s.price.toFixed(2)} \uB9E4\uC218 \uC644\uB8CC
` : `  \u274C ${s.symbol} \uB9E4\uC218 \uC2E4\uD328
`;
          }
          buyMsg += "\n";
        }
      }
    }
    msg += buyMsg + sellMsg;
    return msg;
  } catch (e) {
    return "\u26A0\uFE0F \uC2B9\uC778 \uCC98\uB9AC \uC5D0\uB7EC: " + e.message;
  }
}
__name(executeApproval, "executeApproval");
async function handleApproval(env) {
  if (isMarketOpen()) {
    return await executeApproval(env);
  } else {
    if (env.KV) {
      await env.KV.put("pending_approval", JSON.stringify({
        type: "approval",
        requested_at: (/* @__PURE__ */ new Date()).toISOString()
      }));
      return '\u2705 *\uC2B9\uC778 \uC608\uC57D \uC644\uB8CC!*\n\n\u{1F552} \uBBF8\uAD6D \uC7A5 \uAC1C\uC7A5(23:30 KST) \uC2DC \uC790\uB3D9 \uB9E4\uC218/\uB9E4\uB3C4\uB97C \uC2E4\uD589\uD569\uB2C8\uB2E4.\n\u{1F4E5} \uACB0\uACFC\uB294 \uD154\uB808\uADF8\uB7A8\uC73C\uB85C \uC54C\uB824\uB4DC\uB9AC\uACA0\uC2B5\uB2C8\uB2E4, \uB300\uD45C\uB2D8.\n\n\uCDE8\uC18C\uD558\uB824\uBA74 "\uC608\uC57D\uCDE8\uC18C" \uB77C\uACE0 \uC785\uB825\uD574 \uC8FC\uC138\uC694.';
    } else {
      return "\u26A0\uFE0F KV \uC800\uC7A5\uC18C\uAC00 \uC5F0\uACB0\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4.";
    }
  }
}
__name(handleApproval, "handleApproval");
async function handleReject(env) {
  return "\u{1F6E1}\uFE0F *\uBC18\uB824 \uCC98\uB9AC \uC644\uB8CC*\n\n\uD604\uC7AC \uD3EC\uD2B8\uD3F4\uB9AC\uC624\uB97C \uC720\uC9C0\uD569\uB2C8\uB2E4, \uB300\uD45C\uB2D8.";
}
__name(handleReject, "handleReject");
async function handleTotalReturn(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0) {
      const bp = await getBuyingPower(env);
      const usd = bp ? bp.ord_psbl_frcr_amt : "\uC870\uD68C \uC2E4\uD328";
      return "\u{1F4CA} *\uC804\uCCB4 \uC218\uC775\uB960*\n\n\u{1F4ED} \uD604\uC7AC \uBCF4\uC720 \uC885\uBAA9\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.\n\u{1F4B0} \uC608\uC218\uAE08: *$" + usd + "*\n\n\uD604\uAE08 100% \uC0C1\uD0DC\uC785\uB2C8\uB2E4, \uB300\uD45C\uB2D8! \u{1F6E1}\uFE0F";
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
    const rate = totalInvested > 0 ? totalPnl / totalInvested * 100 : 0;
    const emoji = totalPnl >= 0 ? "\u{1F680}" : "\u{1F4C9}";
    const activeCount = holdings.filter((h) => parseInt(h.ovrs_cblc_qty || "0") > 0).length;
    return "\u{1F4CA} *\uC804\uCCB4 \uC218\uC775\uB960*\n\n\u{1F4B0} \uCD1D \uD3C9\uAC00\uAE08\uC561: *$" + totalEval.toFixed(2) + "*\n\u{1F4B5} \uD22C\uC790 \uC6D0\uAE08: $" + totalInvested.toFixed(2) + "\n" + emoji + " \uB204\uC801 \uC218\uC775\uB960: *" + (rate >= 0 ? "+" : "") + rate.toFixed(1) + "%* (" + (totalPnl >= 0 ? "+" : "") + totalPnl.toFixed(2) + ")\n\u{1F4CB} \uBCF4\uC720 \uC885\uBAA9: " + activeCount + "\uAC1C";
  } catch (e) {
    return "\u26A0\uFE0F \uC870\uD68C \uC5D0\uB7EC: " + e.message;
  }
}
__name(handleTotalReturn, "handleTotalReturn");
async function handleStockReturn(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0)
      return "\u{1F4C8} *\uC885\uBAA9\uBCC4 \uC218\uC775\uB960*\n\n\u{1F4ED} \uBCF4\uC720 \uC885\uBAA9\uC774 \uC5C6\uC2B5\uB2C8\uB2E4, \uB300\uD45C\uB2D8.";
    let msg = "\u{1F4C8} *\uC885\uBAA9\uBCC4 \uC218\uC775\uB960*\n\n";
    const active = holdings.filter((h) => parseInt(h.ovrs_cblc_qty || "0") > 0);
    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const buyAvg = parseFloat(h.pchs_avg_pric || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const pnlRt = parseFloat(h.evlu_pfls_rt || "0");
      const pnl = parseFloat(h.frcr_evlu_pfls_amt || "0");
      const emoji = pnl >= 0 ? "\u{1F7E2}" : "\u{1F534}";
      msg += emoji + " *" + sym + "* (" + (pnlRt >= 0 ? "+" : "") + pnlRt.toFixed(1) + "%)\n   " + qty + "\uC8FC | \uB9E4\uC785 $" + buyAvg.toFixed(2) + " \u2192 \uD604\uC7AC $" + cur.toFixed(2) + "\n   \uC190\uC775: " + (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "\n\n";
    }
    if (active.length > 0) {
      const best = active.reduce((a, b) => parseFloat(a.evlu_pfls_rt || "0") > parseFloat(b.evlu_pfls_rt || "0") ? a : b);
      msg += "\u{1F3C6} \uD6A8\uC790 \uC885\uBAA9: *" + (best.ovrs_pdno || "?") + "*";
    }
    return msg;
  } catch (e) {
    return "\u26A0\uFE0F \uC870\uD68C \uC5D0\uB7EC: " + e.message;
  }
}
__name(handleStockReturn, "handleStockReturn");
async function handleDeposit(env) {
  try {
    const bp = await getBuyingPower(env);
    if (!bp) return "\u26A0\uFE0F \uC608\uC218\uAE08 \uC870\uD68C\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.";
    const usd = bp.ord_psbl_frcr_amt || "0";
    const holdings = await getBalance(env);
    let cashRatio = 100;
    if (holdings && holdings.length > 0) {
      const totalEval = holdings.reduce((sum, h) => {
        const qty = parseInt(h.ovrs_cblc_qty || "0");
        return qty > 0 ? sum + parseFloat(h.now_pric2 || "0") * qty : sum;
      }, 0);
      const totalAsset = totalEval + parseFloat(usd);
      cashRatio = totalAsset > 0 ? parseFloat(usd) / totalAsset * 100 : 100;
    }
    let advice = "\u{1F6E1}\uFE0F \uB300\uBD80\uBD84 \uD604\uAE08 \uBCF4\uC720 \uC911\uC785\uB2C8\uB2E4. \uC548\uC804\uD55C \uC0C1\uD0DC\uC785\uB2C8\uB2E4!";
    if (cashRatio < 50) advice = "\u{1F4C8} \uD22C\uC790 \uBE44\uC911\uC774 \uB192\uC2B5\uB2C8\uB2E4. \uC2DC\uC7A5 \uBCC0\uB3D9\uC5D0 \uC720\uC758\uD574 \uC8FC\uC138\uC694.";
    else if (cashRatio < 80) advice = "\u2696\uFE0F \uC801\uC808\uD55C \uD604\uAE08 \uBE44\uC911\uC744 \uC720\uC9C0\uD558\uACE0 \uC788\uC2B5\uB2C8\uB2E4.";
    return "\u{1F4B5} *\uC608\uC218\uAE08 \uD604\uD669*\n\n\u{1F4B0} \uC989\uC2DC \uB9E4\uC218 \uAC00\uB2A5: *$" + usd + "*\n\u{1F4CA} \uD604\uAE08 \uBE44\uC911: " + cashRatio.toFixed(0) + "%\n\n" + advice;
  } catch (e) {
    return "\u26A0\uFE0F \uC870\uD68C \uC5D0\uB7EC: " + e.message;
  }
}
__name(handleDeposit, "handleDeposit");
async function handleBalance(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0)
      return "\u{1F4B0} *\uC2E4\uC2DC\uAC04 \uC794\uACE0*\n\n\u{1F4ED} \uBCF4\uC720 \uC885\uBAA9 \uC5C6\uC74C. \uD604\uAE08 100% \uC0C1\uD0DC\uC785\uB2C8\uB2E4.";
    const active = holdings.filter((h) => parseInt(h.ovrs_cblc_qty || "0") > 0);
    let totalEval = 0;
    let msg = "\u{1F4B0} *\uC2E4\uC2DC\uAC04 \uC794\uACE0*\n\n\u{1F4CB} \uD604\uC7AC *" + active.length + "\uC885\uBAA9* \uBCF4\uC720 \uC911:\n";
    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const evalAmt = cur * qty;
      totalEval += evalAmt;
      msg += "  \u2022 *" + sym + "*: " + qty + "\uC8FC \xD7 $" + cur.toFixed(2) + " = $" + evalAmt.toFixed(2) + "\n";
    }
    msg += "\n\u{1F4C8} \uCD1D \uD3C9\uAC00\uC561: *$" + totalEval.toFixed(2) + "*";
    return msg;
  } catch (e) {
    return "\u26A0\uFE0F \uC870\uD68C \uC5D0\uB7EC: " + e.message;
  }
}
__name(handleBalance, "handleBalance");
async function handleTodayScan(env) {
  try {
    const url = "https://raw.githubusercontent.com/abraxass0511-lab/Alpha-Investment-Agent/main/output_reports/metadata.json";
    const r = await fetch(url);
    if (!r.ok) return "\u{1F50D} *\uC624\uB298\uC790 \uC2A4\uCE94*\n\n\u274C \uC544\uC9C1 \uC624\uB298 \uC2A4\uCE94\uC774 \uC2E4\uD589\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4.";
    const meta = await r.json();
    const scanTime = (meta.timestamp || "N/A").substring(0, 16);
    const step6 = meta.step6 || 0;
    let msg = "\u{1F50D} *\uC624\uB298\uC790 \uC2A4\uCE94 \uACB0\uACFC*\n\n\u{1F4C5} \uC2A4\uCE94 \uC2DC\uAC01: " + scanTime + "\n\n";
    msg += "`1+2\uB2E8\uACC4` \uCCB4\uAE09+\uB0B4\uC2E4 : " + (meta.total || 503) + " \u2192 *" + (meta.step12 || meta.step1 || 0) + "\uAC74*\n";
    msg += "`3\uB2E8\uACC4` \uC5D0\uB108\uC9C0 : \u2192 *" + (meta.step3 || 0) + "\uAC74*\n";
    msg += "`4\uB2E8\uACC4` \uC131\uC7A5   : \u2192 *" + (meta.step4 || 0) + "\uAC74*\n";
    msg += "`5\uB2E8\uACC4` \uC2EC\uB9AC   : \u2192 *" + (meta.step5 || 0) + "\uAC74*\n";
    msg += "`6\uB2E8\uACC4` \uAE30\uC138   : \u2192 *" + (meta.step6 || 0) + "\uAC74*\n\n";
    msg += step6 > 0 ? "\u{1F525} \uCD5C\uC885 \uD1B5\uACFC \uC885\uBAA9 *" + step6 + "\uAC1C*! \uB9AC\uD3EC\uD2B8\uB97C \uD655\uC778\uD574 \uC8FC\uC138\uC694." : "\u{1F6E1}\uFE0F \uC624\uB298\uC740 \uAE30\uC900 \uCDA9\uC871 \uC885\uBAA9\uC774 \uC5C6\uC2B5\uB2C8\uB2E4. \uD604\uAE08 \uBCF4\uC720 \uAD8C\uACE0!";
    return msg;
  } catch (e) {
    return "\u26A0\uFE0F \uC870\uD68C \uC5D0\uB7EC: " + e.message;
  }
}
__name(handleTodayScan, "handleTodayScan");
async function handleEmergencySell(env) {
  return '\u{1F6D1} *\uAE34\uAE09 \uC804\uB7C9 \uB9E4\uB3C4 \uD655\uC778*\n\n\u26A0\uFE0F \uBAA8\uB4E0 \uBCF4\uC720 \uC885\uBAA9\uC744 \uB9E4\uB3C4\uD569\uB2C8\uB2E4.\n\u2022 \uC7A5 \uC5F4\uB9BC: \uC989\uC2DC \uC2E4\uD589\n\u2022 \uC7A5 \uB2EB\uD798: \uAC1C\uC7A5(23:30) \uC608\uC57D\n\n\uC815\uB9D0 \uC2E4\uD589\uD558\uC2DC\uACA0\uC2B5\uB2C8\uAE4C?\n\u2192 "\uC804\uB7C9\uB9E4\uB3C4" \uB77C\uACE0 \uC785\uB825\uD574 \uC8FC\uC138\uC694.\n\u2192 \uC608\uC57D \uD6C4 \uCDE8\uC18C: "\uC608\uC57D\uCDE8\uC18C" \uC785\uB825 (23:30 \uC804\uAE4C\uC9C0)';
}
__name(handleEmergencySell, "handleEmergencySell");
var US_HOLIDAYS = [
  "2026-01-01",
  "2026-01-19",
  "2026-02-16",
  "2026-04-03",
  "2026-05-25",
  "2026-06-19",
  "2026-07-03",
  "2026-09-07",
  "2026-11-26",
  "2026-12-25",
  "2027-01-01",
  "2027-01-18",
  "2027-02-15",
  "2027-03-26",
  "2027-05-31",
  "2027-06-18",
  "2027-07-05",
  "2027-09-06",
  "2027-11-25",
  "2027-12-24"
];
function isTradingDay(dateObj) {
  const utcDay = dateObj.getUTCDay();
  if (utcDay === 0 || utcDay === 6) return false;
  const ymd = dateObj.toISOString().split("T")[0];
  if (US_HOLIDAYS.includes(ymd)) return false;
  return true;
}
__name(isTradingDay, "isTradingDay");
function isMarketOpen() {
  const now = /* @__PURE__ */ new Date();
  if (!isTradingDay(now)) return false;
  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();
  const utcMin = utcH * 60 + utcM;
  return utcMin >= 13 * 60 + 30 && utcMin < 21 * 60;
}
__name(isMarketOpen, "isMarketOpen");
async function handleSellConfirm(env) {
  if (isMarketOpen()) {
    return await executeEmergencySell(env);
  } else {
    if (env.KV) {
      await env.KV.put("pending_sell", JSON.stringify({
        type: "sell_all",
        requested_at: (/* @__PURE__ */ new Date()).toISOString()
      }));
      return '\u2705 *\uB9E4\uB3C4 \uC608\uC57D \uC644\uB8CC!*\n\n\u{1F552} \uBBF8\uAD6D \uC7A5 \uAC1C\uC7A5(23:30 KST) \uC2DC \uC790\uB3D9 \uC2E4\uD589\uD569\uB2C8\uB2E4.\n\u{1F4E9} \uACB0\uACFC\uB294 \uD154\uB808\uADF8\uB7A8\uC73C\uB85C \uC54C\uB824\uB4DC\uB9AC\uACA0\uC2B5\uB2C8\uB2E4, \uB300\uD45C\uB2D8.\n\n\uCDE8\uC18C\uD558\uB824\uBA74 "\uC608\uC57D\uCDE8\uC18C" \uB77C\uACE0 \uC785\uB825\uD574 \uC8FC\uC138\uC694.';
    } else {
      return "\u26A0\uFE0F KV \uC800\uC7A5\uC18C\uAC00 \uC5F0\uACB0\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4.";
    }
  }
}
__name(handleSellConfirm, "handleSellConfirm");
async function handleCancelReservation(env) {
  if (env.KV) {
    let cancelled = false;
    const p1 = await env.KV.get("pending_sell");
    if (p1) {
      await env.KV.delete("pending_sell");
      cancelled = true;
    }
    const p2 = await env.KV.get("pending_approval");
    if (p2) {
      await env.KV.delete("pending_approval");
      cancelled = true;
    }
    if (cancelled) {
      return "\u274C *\uC608\uC57D\uC774 \uC815\uC0C1\uC801\uC73C\uB85C \uCDE8\uC18C\uB418\uC5C8\uC2B5\uB2C8\uB2E4.*\n\n\u{1F6E1}\uFE0F \uC608\uC57D\uB41C \uC8FC\uBB38\uC774 \uC81C\uAC70\uB418\uC5C8\uC73C\uBA70, \uD604\uC7AC \uD3EC\uD2B8\uD3F4\uB9AC\uC624\uB97C \uC720\uC9C0\uD569\uB2C8\uB2E4, \uB300\uD45C\uB2D8.";
    }
  }
  return "\u26A0\uFE0F \uCDE8\uC18C\uD560 \uC608\uC57D(\uC2B9\uC778 \uB300\uAE30 \uAC74 \uB610\uB294 \uB9E4\uB3C4 \uB300\uAE30 \uAC74)\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.";
}
__name(handleCancelReservation, "handleCancelReservation");
async function executeEmergencySell(env) {
  try {
    const holdings = await getBalance(env);
    if (!holdings || holdings.length === 0)
      return "\u{1F4ED} \uBCF4\uC720 \uC885\uBAA9\uC774 \uC5C6\uC2B5\uB2C8\uB2E4. \uC774\uBBF8 \uD604\uAE08 100% \uC0C1\uD0DC\uC785\uB2C8\uB2E4.";
    const active = holdings.filter((h) => parseInt(h.ovrs_cblc_qty || "0") > 0);
    if (active.length === 0) return "\u{1F4ED} \uBCF4\uC720 \uC885\uBAA9\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.";
    let msg = "\u{1F6D1} *[\uC804\uB7C9 \uB9E4\uB3C4 \uC2E4\uD589]*\n\n";
    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const sellPrice = (cur * 0.995).toFixed(2);
      const success = await sellOrder(env, sym, qty, sellPrice);
      const status = success ? "\u2705 \uC644\uB8CC" : "\u274C \uC2E4\uD328";
      msg += "  " + status + " *" + sym + "* " + qty + "\uC8FC \xD7 $" + sellPrice + "\n";
    }
    msg += "\n\u{1F6E1}\uFE0F \uB9E4\uB3C4 \uCC98\uB9AC\uAC00 \uC644\uB8CC\uB418\uC5C8\uC2B5\uB2C8\uB2E4, \uB300\uD45C\uB2D8.";
    return msg;
  } catch (e) {
    return "\u26A0\uFE0F \uB9E4\uB3C4 \uC5D0\uB7EC: " + e.message;
  }
}
__name(executeEmergencySell, "executeEmergencySell");
async function handleAiChat(env, question) {
  try {
    if (!env.GEMINI_API_KEY) return "\u26A0\uFE0F AI \uC5D4\uC9C4\uC774 \uC5F0\uACB0\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4.";
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${env.GEMINI_API_KEY}`;
    let ctx = "";
    try {
      const holdings = await getBalance(env);
      if (holdings && holdings.length > 0) {
        ctx += "### Portfolio\n";
        for (const h of holdings) {
          const qty = parseInt(h.ovrs_cblc_qty || "0");
          if (qty <= 0) continue;
          ctx += "- " + h.ovrs_pdno + ": " + qty + " shares, buy $" + parseFloat(h.pchs_avg_pric || "0").toFixed(2) + ", now $" + parseFloat(h.now_pric2 || "0").toFixed(2) + ", return " + parseFloat(h.evlu_pfls_rt || "0").toFixed(1) + "%\n";
        }
      }
    } catch {
    }
    const systemPrompt = `\uB108\uB294 '\uC5D0\uC774\uC804\uD2B8 \uC54C\uD30C'\uC57C. \uBBF8\uAD6D \uC8FC\uC2DD \uD22C\uC790\uB97C \uC804\uB2F4\uD558\uB294 AI \uBE44\uC11C.
\uD56D\uC0C1 "\uB300\uD45C\uB2D8"\uC774\uB77C\uACE0 \uD638\uCE6D. \uAC04\uACB0\uD558\uACE0 \uD575\uC2EC \uC704\uC8FC. \uB370\uC774\uD130 \uAE30\uBC18 \uB2F5\uBCC0\uB9CC. \uD154\uB808\uADF8\uB7A8 Markdown \uD615\uC2DD. \uB2F5\uBCC0 300\uC790 \uC774\uB0B4. \uC774\uBAA8\uC9C0 \uC0AC\uC6A9.
` + ctx;
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: systemPrompt }] },
        contents: [{ parts: [{ text: question }] }],
        generationConfig: { temperature: 0.7, maxOutputTokens: 500 }
      })
    });
    if (r.status === 429) return "\u26A0\uFE0F AI \uBB34\uB8CC \uC81C\uACF5\uB7C9 \uCD08\uACFC. \uC7A0\uC2DC \uD6C4 \uB2E4\uC2DC \uC2DC\uB3C4\uD574 \uC8FC\uC138\uC694.";
    if (!r.ok) return "\u26A0\uFE0F AI \uC751\uB2F5 \uC5D0\uB7EC (HTTP " + r.status + ")";
    const data = await r.json();
    return data.candidates[0].content.parts[0].text.trim();
  } catch (e) {
    return "\u26A0\uFE0F AI \uC5D0\uB7EC: " + e.message;
  }
}
__name(handleAiChat, "handleAiChat");
var TEXT_HANDLERS = {
  "\u{1F4CA} \uC804\uCCB4 \uC218\uC775\uB960": handleTotalReturn,
  "\u{1F4C8} \uC885\uBAA9\uBCC4 \uC218\uC775\uB960": handleStockReturn,
  "\u{1F4B5} \uC608\uC218\uAE08 \uD604\uD669": handleDeposit,
  "\u{1F4B0} \uC2E4\uC2DC\uAC04 \uC794\uACE0": handleBalance,
  "\u{1F50D} \uC624\uB298\uC790 \uC2A4\uCE94": handleTodayScan,
  "\u{1F6D1} \uAE34\uAE09 \uC804\uB7C9 \uB9E4\uB3C4": handleEmergencySell
};
async function handleUpdate(update, env) {
  if (!update.message) return;
  const msg = update.message;
  const text = (msg.text || "").trim();
  const fromId = String(msg.from?.id || "");
  if (fromId !== String(env.TELEGRAM_CHAT_ID)) return;
  if (["/menu", "/start"].includes(text.toLowerCase()) || text === "\uBA54\uB274") {
    await sendMessage(env, "\u{1F916} *\uC54C\uD30C \uC5D0\uC774\uC804\uD2B8 \uBA54\uB274*\n\n\uD558\uB2E8 \uBC84\uD2BC\uC744 \uB20C\uB7EC\uC8FC\uC138\uC694, \uB300\uD45C\uB2D8!", REPLY_KEYBOARD);
    return;
  }
  if (text === "\uC804\uB7C9\uB9E4\uB3C4") {
    const response2 = await handleSellConfirm(env);
    await sendMessage(env, response2, REPLY_KEYBOARD);
    return;
  }
  if (text === "\uC608\uC57D\uCDE8\uC18C") {
    const response2 = await handleCancelReservation(env);
    await sendMessage(env, response2, REPLY_KEYBOARD);
    return;
  }
  if (TEXT_HANDLERS[text]) {
    const response2 = await TEXT_HANDLERS[text](env);
    await sendMessage(env, response2, REPLY_KEYBOARD);
    return;
  }
  if (text === "\uC2DC\uB3C4") {
    if (!env.GITHUB_PAT) {
      await sendMessage(env, "\u26A0\uFE0F GitHub \uC5F0\uB3D9\uC774 \uC124\uC815\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4.", REPLY_KEYBOARD);
      return;
    }
    const r = await fetch("https://api.github.com/repos/abraxass0511-lab/Alpha-Investment-Agent/actions/workflows/alpha_daily.yml/dispatches", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_PAT}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "Alpha-Bot"
      },
      body: JSON.stringify({ ref: "main" })
    });
    if (r.ok || r.status === 204) {
      await sendMessage(env, "\u{1F504} *\uC2A4\uCE94 \uC7AC\uC2DC\uB3C4 \uC2DC\uC791!*\n\n\uC57D 20~30\uBD84 \uD6C4 \uACB0\uACFC\uB97C \uC54C\uB824\uB4DC\uB9AC\uACA0\uC2B5\uB2C8\uB2E4, \uB300\uD45C\uB2D8.", REPLY_KEYBOARD);
    } else {
      await sendMessage(env, "\u26A0\uFE0F \uC7AC\uC2DC\uB3C4 \uC694\uCCAD \uC2E4\uD328 (HTTP " + r.status + ")", REPLY_KEYBOARD);
    }
    return;
  }
  if (text === "\uC885\uB8CC") {
    await sendMessage(env, "\u2705 *\uC624\uB298 \uC2A4\uCE94\uC744 \uAC74\uB108\uB6F5\uB2C8\uB2E4.*\n\n\uB0B4\uC77C \uC815\uC0C1 \uC2E4\uD589\uB429\uB2C8\uB2E4, \uB300\uD45C\uB2D8.", REPLY_KEYBOARD);
    return;
  }
  if (text === "\uC2B9\uC778") {
    const response2 = await handleApproval(env);
    await sendMessage(env, response2, REPLY_KEYBOARD);
    return;
  }
  if (text === "\\ubc18\\ub824") {
    const response2 = await handleReject(env);
    await sendMessage(env, response2, REPLY_KEYBOARD);
    return;
  }
  const response = await handleAiChat(env, text);
  await sendMessage(env, response, REPLY_KEYBOARD);
}
__name(handleUpdate, "handleUpdate");
export {
  worker_default as default
};
//# sourceMappingURL=worker.js.map
