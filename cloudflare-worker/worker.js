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

          // ★ 체결내역 RAW 조회 (필드명 검증용)
          const fillUrl = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-ccnl`;
          const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
          const kstDate = kstNow.toISOString().slice(0, 10).replace(/-/g, "");
          const fillParams = new URLSearchParams({
            CANO: env.KIS_CANO, ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
            PDNO: "", ORD_STRT_DT: kstDate, ORD_END_DT: kstDate,
            SLL_BUY_DVSN: "00", CCLD_NCCS_DVSN: "00",
            OVRS_EXCG_CD: "", SORT_SQN: "DS",
            ORD_DT: "", ORD_GNO_BRNO: "", ODNO: "",
            CTX_AREA_NK200: "", CTX_AREA_FK200: "",
          });
          const fillR = await fetch(`${fillUrl}?${fillParams}`, {
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
              appkey: env.KIS_APP_KEY, appsecret: env.KIS_SECRET_KEY,
              "tr_id": "VTTS3035R",
            },
          });
          results.fills_raw = await fillR.json();
          results.fills_query_date = kstDate;

          // ★ 첫 번째 체결 레코드의 필드명 표시 (디버깅용)
          if (results.fills_raw.output && results.fills_raw.output.length > 0) {
            results.fills_first_record_keys = Object.keys(results.fills_raw.output[0]);
            results.fills_first_record = results.fills_raw.output[0];
          }

          // Check KV states
          if (env.KV) {
            results.pending_sell = await env.KV.get("pending_sell");
            results.pending_fill_check = await env.KV.get("pending_fill_check");
            results.pending_approval = await env.KV.get("pending_approval");
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

    // ✅ 토큰 동기화: GitHub Actions에서 발급한 토큰을 Worker KV에 저장
    if (url.pathname === "/api/sync-token" && request.method === "POST") {
      try {
        const authHeader = request.headers.get("Authorization") || "";
        if (authHeader !== `Bearer ${env.WORKER_API_KEY || "alpha-internal"}`) {
          return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
        }

        const body = await request.json();
        const { token } = body;
        if (!token) {
          return new Response(JSON.stringify({ error: "Missing token" }), { status: 400 });
        }

        const now = Date.now();
        // 인메모리 캐시 업데이트
        _cachedToken = token;
        _tokenIssuedAt = now;

        // KV에 저장
        if (env.KV) {
          await env.KV.put(KV_TOKEN_KEY, JSON.stringify({
            token: token,
            issued_at: now,
          }), { expirationTtl: 86400 });
        }

        console.log("✅ 토큰 동기화 완료 (Actions → Worker)");
        return new Response(JSON.stringify({ success: true, synced_at: new Date().toISOString() }), {
          headers: { "Content-Type": "application/json" },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" },
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

        const result = await sellOrder(env, symbol, parseInt(qty), String(price));
        return new Response(JSON.stringify({ success: result.success, error: result.error || null, symbol, qty, price }), {
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
      const isTradingDayNow = isTradingDay(new Date());

      // === A-0. Stale pending_fill_check 자동 정리 (거래일 무관) ===
      // 날짜가 바뀌었으면 잔고 기반으로 체결 여부 확인 후 정리
      {
        const fillPendStale = await env.KV.get("pending_fill_check");
        if (fillPendStale) {
          const staleData = JSON.parse(fillPendStale);
          const orderDateKst = staleData.order_date_kst || null;
          const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
          const todayKst = kstNow.toISOString().slice(0, 10);

          if (orderDateKst && orderDateKst !== todayKst) {
            // 잔고에서 해당 종목 보유 여부로 체결 판단
            const symbols = staleData.symbols || [];
            const holdings = await getBalance(env);
            const heldSymbols = (holdings || [])
              .filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0)
              .map(h => h.ovrs_pdno || "");
            const filled = symbols.filter(s => heldSymbols.includes(s));
            const notFilled = symbols.filter(s => !heldSymbols.includes(s));

            let staleMsg = "📊 *[체결 확인 완료]*\n━━━━━━━━━━━━━━━\n\n";
            staleMsg += `📅 주문일: ${orderDateKst}\n\n`;
            if (filled.length > 0) {
              staleMsg += `✅ 체결 확인: ${filled.join(", ")}\n`;
              staleMsg += "_잔고에서 보유 확인됨_\n\n";
            }
            if (notFilled.length > 0) {
              staleMsg += `❌ 미체결: ${notFilled.join(", ")}\n`;
            }
            if (filled.length === 0 && notFilled.length === 0) {
              staleMsg += "⚠️ 추적 종목 정보 없음\n";
            }
            staleMsg += "\n_실시간 알림이 지연되어 잔고 기반으로 확인했습니다._";
            await sendMessage(env, staleMsg, REPLY_KEYBOARD);
            await env.KV.delete("pending_fill_check");
            // stale 정리 완료 → 이하 체결 폴링 스킵 (fillPend 이미 삭제됨)
          }
        }
      }

      // === A. 체결 확인 폴링 (거래일 + 오늘 주문건만) ===
      if (isTradingDayNow) {
        const fillPend = await env.KV.get("pending_fill_check");
        if (fillPend) {
          const fillData = JSON.parse(fillPend);
          const etHour = getETHour();
          // ★ KV에 저장된 주문 날짜(KST)로 조회 — UTC/KST 불일치 방지
          const orderDateKst = fillData.order_date_kst || null;
          // ★ 폴링 횟수 추적 (무한 대기 방지)
          const pollCount = (fillData.poll_count || 0) + 1;
          // ★ 이미 알림 보낸 종목 추적 (중복 알림 방지)
          const alreadyNotified = fillData.notified_symbols || [];

          // (stale 정리는 A-0에서 이미 수행됨 → 여기는 오늘 주문건만 도달)
          const orders = await checkOrderFills(env, orderDateKst);

          if (!orders) {
            // API 실패 시: 10회 이상 실패하면 대표님께 알림
            if (pollCount >= 10 || (etHour >= 16 && etHour < 21)) {
              await sendMessage(env, "⚠️ *[체결 확인 실패]*\n\n체결 내역 조회에 반복 실패했습니다.\nKIS API 응답 오류입니다, 대표님.\n\n💱 KIS 앱에서 직접 체결 여부를 확인해 주세요.", REPLY_KEYBOARD);
              await env.KV.delete("pending_fill_check");
            } else {
              // 폴링 카운트만 증가시키고 다음 cron에서 재시도
              await env.KV.put("pending_fill_check", JSON.stringify({
                ...fillData, poll_count: pollCount,
              }));
            }
          } else {
            const symbols = fillData.symbols || [];
            let filledSymbols = [];
            let unfilledSymbols = [];

            if (orders.length > 0) {
              // 주문 내역에서 우리가 관심 있는 종목만 필터
              const relevantOrders = orders.filter(ord => {
                const sym = ord.pdno || ord.ovrs_pdno || "?";
                return symbols.length === 0 || symbols.includes(sym);
              });

              for (const ord of relevantOrders) {
                const sym = ord.pdno || ord.ovrs_pdno || "?";
                const side = ord.sll_buy_dvsn_cd === "02" ? "매수" : "매도";
                const ordQty = parseInt(ord.ft_ord_qty || ord.ord_qty || "0");
                // ★ ft_ 접두사 필드 우선 (모의투자 API는 ft_ 필드 사용)
                const fillQty = parseInt(ord.ft_ccld_qty || ord.ccld_qty || ord.tot_ccld_qty || "0");
                const fillPrice = ord.ft_ccld_unpr3 || ord.avg_prvs || ord.avg_prc || "0";

                if (fillQty > 0) {
                  filledSymbols.push(sym);
                } else {
                  unfilledSymbols.push({ sym, side, ordQty });
                }
              }

              // 주문 내역에 없는 종목도 미체결로 처리
              const orderedSymsInResult = relevantOrders.map(o => o.pdno || o.ovrs_pdno || "");
              for (const sym of symbols) {
                if (!orderedSymsInResult.includes(sym) && !filledSymbols.includes(sym)) {
                  unfilledSymbols.push({ sym, side: "매수", ordQty: 0 });
                }
              }
            } else {
              // 주문 내역 0건 — 모든 심볼이 미체결
              for (const sym of symbols) {
                unfilledSymbols.push({ sym, side: "매수", ordQty: 0 });
              }
            }

            // ★ 새로 체결된 종목만 추출 (이미 알림 보낸 건 제외)
            const newlyFilled = filledSymbols.filter(s => !alreadyNotified.includes(s));
            const filledAll = unfilledSymbols.length === 0 && filledSymbols.length > 0;

            // ★★★ 핵심 개선: 새로 체결된 종목이 있으면 즉시 알림 ★★★
            if (newlyFilled.length > 0) {
              let msg = "📊 *[체결 알림]*\n━━━━━━━━━━━━━━━\n\n";

              // 체결 내역 상세 표시
              for (const ord of (orders || [])) {
                const sym = ord.pdno || ord.ovrs_pdno || "?";
                if (!newlyFilled.includes(sym)) continue;
                const side = ord.sll_buy_dvsn_cd === "02" ? "매수" : "매도";
                // ★ ft_ 접두사 필드 우선 (모의투자 API는 ft_ 필드 사용)
                const fillQty = parseInt(ord.ft_ccld_qty || ord.ccld_qty || ord.tot_ccld_qty || "0");
                const fillPrice = ord.ft_ccld_unpr3 || ord.avg_prvs || ord.avg_prc || "0";
                const emoji = side === "매수" ? "✅" : "🔻";
                msg += `${emoji} *${sym}* ${side} 체결 완료!\n`;
                msg += `   📊 ${fillQty}주 × $${parseFloat(fillPrice).toFixed(2)}\n\n`;
              }

              if (filledAll) {
                msg += "🎉 _전종목 체결 완료!_";
                await sendMessage(env, msg, REPLY_KEYBOARD);
                await env.KV.delete("pending_fill_check");
              } else {
                // 부분 체결: 체결 알림 + 미체결 현황
                msg += "⏳ *미체결 종목:*\n";
                for (const u of unfilledSymbols) {
                  msg += `  ⚠️ ${u.sym} — 체결 대기 중\n`;
                }
                await sendMessage(env, msg, REPLY_KEYBOARD);
                // 미체결 건 계속 추적 (이미 알린 종목은 기록)
                const updatedNotified = [...new Set([...alreadyNotified, ...newlyFilled])];
                await env.KV.put("pending_fill_check", JSON.stringify({
                  ...fillData,
                  poll_count: pollCount,
                  notified_symbols: updatedNotified,
                }));
              }
            }

            // ★ 장 마감 후 처리: 미체결 건 최종 정리 (체결 알림을 이미 보냈으면 중복 방지)
            else if (etHour >= 16 && etHour < 21) {
              if (filledAll) {
                // 이미 위에서 알림 보냄 → KV만 삭제
                await env.KV.delete("pending_fill_check");
              } else if (unfilledSymbols.length > 0) {
                let closeMsg = "⏰ *[장 마감 정리]*\n━━━━━━━━━━━━━━━\n\n";
                if (filledSymbols.length > 0) {
                  closeMsg += `✅ 체결 완료: ${filledSymbols.join(", ")}\n`;
                }
                closeMsg += `❌ 미체결 (자동취소): ${unfilledSymbols.map(u => u.sym).join(", ")}\n\n`;
                closeMsg += "_미체결 종목은 지정가(+15%) 초과 급등으로 체결되지 못했습니다._";
                await sendMessage(env, closeMsg, REPLY_KEYBOARD);
                await env.KV.delete("pending_fill_check");
              } else if (filledSymbols.length === 0) {
                // 주문 내역 자체가 0건인 경우
                await sendMessage(env, "⚠️ *[장 마감]*\n\n오늘 주문 내역이 조회되지 않았습니다.\n💱 KIS 앱에서 직접 확인해 주세요, 대표님.", REPLY_KEYBOARD);
                await env.KV.delete("pending_fill_check");
              }
            }

            // ★ 장중인데 새로 체결된 것도 없으면 → KV에 폴링 카운트만 업데이트
            if (newlyFilled.length === 0 && !(etHour >= 16 && etHour < 21)) {
              await env.KV.put("pending_fill_check", JSON.stringify({
                ...fillData, poll_count: pollCount,
              }));
            }
          }
        }
      }

      // === B. 예약 주문 실행 (휴장일 여부와 무관하게 항상 실행) ===
      // 예약 주문은 장이 열려 있을 때만 실행 (isMarketOpen 체크)
      // 장이 닫혀 있으면 다음 cron에서 재시도

      // 1. 긴급 전량 매도 예약 실행
      const sellPend = await env.KV.get("pending_sell");
      if (sellPend) {
        if (isMarketOpen()) {
          const data = JSON.parse(sellPend);
          if (data.type === "sell_all") {
            const result = await executeEmergencySell(env);
            await sendMessage(env, "\u23f0 *[\uc608\uc57d \ub9e4\ub3c4 \uc2e4\ud589]*\n\n" + result.msg, REPLY_KEYBOARD);
            if (!result.allFailed) {
              await env.KV.delete("pending_sell");
            } else {
              const retryCount = (data.retry_count || 0) + 1;
              if (retryCount >= 6) {
                await env.KV.delete("pending_sell");
                await sendMessage(env, "\u26a0\ufe0f \ub9e4\ub3c4 \uc608\uc57d 6\ud68c \uc5f0\uc18d \uc2e4\ud328. \uc790\ub3d9 \ucde8\uc18c.", REPLY_KEYBOARD);
              } else {
                await env.KV.put("pending_sell", JSON.stringify({ ...data, retry_count: retryCount }));
              }
            }
          } else {
            await env.KV.delete("pending_sell");
          }
        }
        // 장 닫혀 있으면 KV 유지 → 다음 cron에서 재시도
      }

      // 2. 포트폴리오 승인 매수/매도 예약 실행
      const appPend = await env.KV.get("pending_approval");
      if (appPend) {
        if (isMarketOpen()) {
          const data = JSON.parse(appPend);
          if (data.type === "approval") {
            const result = await executeApproval(env);
            if (typeof result === "string") {
              await sendMessage(env, "\u23f0 *[\uc608\uc57d \uc2b9\uc778]*\n\n" + result, REPLY_KEYBOARD);
              const retryCount = (data.retry_count || 0) + 1;
              if (retryCount >= 6) {
                await env.KV.delete("pending_approval");
                await sendMessage(env, "\u26a0\ufe0f \uc2b9\uc778 \uc608\uc57d 6\ud68c \uc5f0\uc18d \uc2e4\ud328. \uc790\ub3d9 \ucde8\uc18c.", REPLY_KEYBOARD);
              } else {
                await env.KV.put("pending_approval", JSON.stringify({ ...data, retry_count: retryCount }));
              }
            } else if (result.successCount > 0) {
              await sendMessage(env, "\u23f0 *[\uc608\uc57d \uc2b9\uc778 \u2192 \uc8fc\ubb38 \uc811\uc218]*\n\n" + result.msg, REPLY_KEYBOARD);
              await saveFillCheckToKV(env, result.orderedSymbols);
              await env.KV.delete("pending_approval");
            } else {
              await sendMessage(env, "\u23f0 *[\uc608\uc57d \uc2b9\uc778]*\n\n" + result.msg + "\n\u26a0\ufe0f \uc804\ubd80 \uc2e4\ud328. \ub2e4\uc74c cron\uc5d0\uc11c \uc7ac\uc2dc\ub3c4.", REPLY_KEYBOARD);
              const retryCount = (data.retry_count || 0) + 1;
              if (retryCount >= 6) {
                await env.KV.delete("pending_approval");
                await sendMessage(env, "\u26a0\ufe0f \uc2b9\uc778 \uc608\uc57d 6\ud68c \uc5f0\uc18d \uc2e4\ud328. \uc790\ub3d9 \ucde8\uc18c.", REPLY_KEYBOARD);
              } else {
                await env.KV.put("pending_approval", JSON.stringify({ ...data, retry_count: retryCount }));
              }
            }
          } else {
            await env.KV.delete("pending_approval");
          }
        }
        // 장 닫혀 있으면 KV 유지 → 다음 cron에서 재시도
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
  const exchanges = ["NASD", "NYSE", "AMEX"];
  let allHoldings = [];
  let tokenExpired = false;

  for (const excg of exchanges) {
    try {
      const params = new URLSearchParams({
        CANO: env.KIS_CANO,
        ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
        OVRS_EXCG_CD: excg,
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
      if (data.rt_cd === "0" && data.output1) {
        allHoldings = allHoldings.concat(data.output1);
        console.log(`✅ ${excg} 잔고 조회 성공: ${data.output1.length}건`);
      } else if (data.rt_cd !== "0") {
        console.log(`⚠️ ${excg} 잔고 조회 실패: ${data.msg1 || JSON.stringify(data)}`);
        // 토큰 만료 에러인 경우만 기록 (개별 거래소 실패는 건너뛰기)
        if ((data.msg1 || "").includes("token") || (data.msg_cd || "").includes("EGW")) {
          tokenExpired = true;
        }
      }
    } catch (e) {
      console.log(`⚠️ ${excg} 잔고 조회 에러: ${e.message}`);
    }
  }

  // 토큰 만료이고 아직 재시도 안 했으면 전체 재시도
  if (tokenExpired && !_retry && allHoldings.length === 0) {
    console.log("🔄 토큰 만료 감지, 갱신 후 전체 재시도...");
    _cachedToken = null;
    _tokenIssuedAt = 0;
    return getBalance(env, true);
  }

  // 중복 제거 (같은 종목이 여러 거래소에서 반환될 경우)
  const seen = new Set();
  return allHoldings.filter(h => {
    const sym = h.ovrs_pdno || "";
    if (seen.has(sym)) return false;
    seen.add(sym);
    return true;
  });
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

// === 거래소 자동 감지 (NAS → NYS → AMS 순회) ===
async function detectExchange(env, symbol) {
  const token = await getKisToken(env);
  if (!token) return "NASD";

  const exchanges = [
    { order: "NASD", price: "NAS" },
    { order: "NYSE", price: "NYS" },
    { order: "AMEX", price: "AMS" },
  ];

  for (const { order, price } of exchanges) {
    try {
      const url = `${env.KIS_BASE_URL}/uapi/overseas-price/v1/quotations/price`;
      const params = new URLSearchParams({ AUTH: "", EXCD: price, SYMB: symbol });
      const r = await fetch(`${url}?${params}`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          appkey: env.KIS_APP_KEY,
          appsecret: env.KIS_SECRET_KEY,
          "tr_id": "HHDFS00000300",
        },
      });
      const data = await r.json();
      if (data.rt_cd === "0" && parseFloat(data.output?.last || "0") > 0) {
        console.log(`🔍 ${symbol} → ${order} (현재가: $${data.output.last})`);
        return order;
      }
    } catch {}
  }
  console.log(`⚠️ ${symbol} 거래소 감지 실패 → NASD 기본값`);
  return "NASD";
}

// === 주문 재시도 유틸리티 (최대 3회, Exponential Backoff) ===
async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function executeOrderWithRetry(env, trId, symbol, qty, price, exchange, maxRetries = 3) {
  const side = trId === "VTTT1002U" ? "매수" : "매도";
  
  // ═══ 모의투자 지정가 전략 ═══
  // 모의투자는 지정가(ORD_DVSN "00")만 지원 — 시장가("01") 사용 불가
  // 핵심: 항상 실시간 현재가를 조회하고, 공격적 마진(+15%/-15%)으로 사실상 시장가 효과
  // → 현재가보다 15% 높은 지정가 매수 = 즉시 현재 시장가로 체결 (초과분은 미사용)
  let orderPrice = "0";

  try {
    const token = await getKisToken(env);
    if (token) {
      const exchMap = { "NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS" };
      const priceExch = exchMap[exchange] || "NAS";
      const pUrl = `${env.KIS_BASE_URL}/uapi/overseas-price/v1/quotations/price`;
      const pParams = new URLSearchParams({ AUTH: "", EXCD: priceExch, SYMB: symbol });
      const pR = await fetch(`${pUrl}?${pParams}`, {
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          appkey: env.KIS_APP_KEY,
          appsecret: env.KIS_SECRET_KEY,
          "tr_id": "HHDFS00000300",
        },
      });
      const pData = await pR.json();
      if (pData.rt_cd === "0" && parseFloat(pData.output?.last || "0") > 0) {
        const lastPrice = parseFloat(pData.output.last);
        // 매수: +15% 마진, 매도: -15% 마진 → 급등/급락에도 확실한 체결 보장
        orderPrice = side === "매수"
          ? (lastPrice * 1.15).toFixed(2)
          : (lastPrice * 0.85).toFixed(2);
        console.log(`💲 ${symbol} 실시간 $${lastPrice} → ${side} 지정가 $${orderPrice} (${side === "매수" ? "+15%" : "-15%"})`);
      }
    }
  } catch (e) {
    console.log(`⚠️ ${symbol} 현재가 조회 실패: ${e.message}`);
  }

  // 실시간 조회 실패 시 CSV 가격에 마진 적용 (폴백)
  if (parseFloat(orderPrice) <= 0 && price && parseFloat(String(price)) > 0) {
    const csvPrice = parseFloat(String(price));
    orderPrice = side === "매수"
      ? (csvPrice * 1.15).toFixed(2)
      : (csvPrice * 0.85).toFixed(2);
    console.log(`⚠️ ${symbol} 폴백: CSV가격 $${csvPrice} → ${side} 지정가 $${orderPrice}`);
  }

  // 가격이 여전히 0이면 주문 불가
  if (parseFloat(orderPrice) <= 0) {
    return { success: false, error: "현재가 조회 실패 (지정가 필요)" };
  }

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const token = await getKisToken(env, attempt > 1); // 재시도 시 토큰 강제 갱신
      if (!token) {
        console.log(`❌ ${side} 실패 ${symbol}: 토큰 발급 실패 (시도 ${attempt}/${maxRetries})`);
        if (attempt < maxRetries) {
          await sleep(1000 * Math.pow(2, attempt - 1)); // 1s, 2s, 4s
          continue;
        }
        return { success: false, error: "토큰 발급 실패" };
      }

      const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order`;
      const r = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          appkey: env.KIS_APP_KEY,
          appsecret: env.KIS_SECRET_KEY,
          "tr_id": trId,
        },
        body: JSON.stringify({
          CANO: env.KIS_CANO,
          ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
          OVRS_EXCG_CD: exchange,
          PDNO: symbol,
          ORD_QTY: String(qty),
          OVRS_ORD_UNPR: orderPrice,
          ORD_SVR_DVSN_CD: "0",
          ORD_DVSN: "00",
        }),
      });

      const data = await r.json();
      
      if (data.rt_cd === "0") {
        if (attempt > 1) {
          console.log(`✅ ${side} 성공 ${symbol}@${exchange} (재시도 ${attempt}회만에 성공)`);
        }
        return { success: true };
      }

      const errMsg = data.msg1 || JSON.stringify(data);
      console.log(`❌ ${side} 실패 ${symbol}@${exchange} (시도 ${attempt}/${maxRetries}): ${errMsg}`);

      // 재시도 불가능한 에러 (잔고 부족, 종목 코드 오류 등)는 즉시 중단
      const noRetryKeywords = ["잔고", "수량", "종목", "거래정지", "매매불가"];
      if (noRetryKeywords.some(kw => errMsg.includes(kw))) {
        return { success: false, error: errMsg };
      }

      if (attempt < maxRetries) {
        await sleep(1000 * Math.pow(2, attempt - 1)); // 1s, 2s
      } else {
        return { success: false, error: errMsg };
      }
    } catch (e) {
      console.log(`❌ ${side} 예외 ${symbol} (시도 ${attempt}/${maxRetries}): ${e.message}`);
      if (attempt < maxRetries) {
        await sleep(1000 * Math.pow(2, attempt - 1));
      } else {
        return { success: false, error: e.message };
      }
    }
  }
  return { success: false, error: "알 수 없는 오류" };
}

async function sellOrder(env, symbol, qty, price, exchange = null) {
  if (!exchange) exchange = await detectExchange(env, symbol);
  return await executeOrderWithRetry(env, "VTTT1006U", symbol, qty, price, exchange);
}

async function buyOrder(env, symbol, qty, price, exchange = null) {
  if (!exchange) exchange = await detectExchange(env, symbol);
  return await executeOrderWithRetry(env, "VTTT1002U", symbol, qty, price, exchange);
}

// === 체결 확인 함수 (KIS 주문체결내역 조회) ===
// ★ KIS API는 KST(한국시간) 기준 날짜를 사용 — UTC 사용 시 날짜 불일치 발생!
async function checkOrderFills(env, orderDate) {
  const token = await getKisToken(env);
  if (!token) return null;

  // orderDate가 있으면 그 날짜 사용, 없으면 KST 기준 오늘
  let queryDate;
  if (orderDate) {
    queryDate = orderDate.replace(/-/g, "");
  } else {
    // KST = UTC+9 기준 오늘 날짜
    const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
    queryDate = kstNow.toISOString().slice(0, 10).replace(/-/g, "");
  }
  console.log(`📅 체결 조회 날짜(KST): ${queryDate}`);

  const url = `${env.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-ccnl`;
  const params = new URLSearchParams({
    CANO: env.KIS_CANO,
    ACNT_PRDT_CD: env.KIS_ACNT_PRDT_CD,
    PDNO: "",
    ORD_STRT_DT: queryDate,
    ORD_END_DT: queryDate,
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
    console.log(`📋 체결 조회 결과: ${(data.output || []).length}건`);
    return data.output || [];
  }
  console.log(`❌ 체결 조회 실패: ${data.msg1 || JSON.stringify(data)}`);
  return null;
}

// KV에 체결 확인 대상 저장 (cron이 5분 간격으로 확인)
// ★ 주문 날짜(KST)를 함께 저장하여, 체결 확인 시 정확한 날짜로 조회
async function saveFillCheckToKV(env, orderedSymbols) {
  if (!env.KV || !orderedSymbols || orderedSymbols.length === 0) return;
  // KST 기준 날짜 저장 (KIS API가 KST 날짜를 사용하므로)
  const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
  const kstDate = kstNow.toISOString().slice(0, 10);
  await env.KV.put("pending_fill_check", JSON.stringify({
    symbols: orderedSymbols,
    ordered_at: new Date().toISOString(),
    order_date_kst: kstDate,
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
    let successCount = 0;

    // \ub9e4\ub3c4 \uba3c\uc800 \uc2e4\ud589 (\uc608\uc218\uae08 \ud655\ubcf4)
    if (sellStocks.length > 0) {
      sellMsg += "\ud83d\udd34 *\ub9e4\ub3c4:*\n";
      for (const s of sellStocks) {
        const res = await sellOrder(env, s.symbol, s.qty, s.current);
        if (res.success) successCount++;
        sellMsg += res.success
          ? `  \u2705 ${s.symbol} ${s.qty}\uc8fc \u00d7 $${s.current.toFixed(2)} \ub9e4\ub3c4 \uc8fc\ubb38 \uc811\uc218\n`
          : `  \u274c ${s.symbol} \ub9e4\ub3c4 \uc2e4\ud328: ${res.error}\n`;
      }
      sellMsg += "\n";
    }

    // \ub9e4\uc218 \uc2e4\ud589
    if (buyStocks.length > 0) {
      const holdings = await getBalance(env);
      const heldSymbols = (holdings || []).filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0).map(h => h.ovrs_pdno);
      buyStocks = buyStocks.filter(s => !heldSymbols.includes(s.symbol));

      // ★ MAX_PORTFOLIO=5 제한: 보유 유지 종목 + 매수 종목 합산 5개까지만
      const MAX_PORTFOLIO = 5;
      const currentHeld = heldSymbols.length;
      const sellCount = sellStocks.length;
      const remainingHeld = Math.max(0, currentHeld - sellCount);
      const availableSlots = Math.max(0, MAX_PORTFOLIO - remainingHeld);
      if (buyStocks.length > availableSlots) {
        console.log(`⚠️ 매수 후보 ${buyStocks.length}개 → ${availableSlots}개로 제한 (보유유지 ${remainingHeld}종목)`);
        buyStocks = buyStocks.slice(0, availableSlots);
      }

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
            // 거래소 자동 감지 후 매수
            const exchange = await detectExchange(env, s.symbol);
            const res = await buyOrder(env, s.symbol, qty, s.price.toFixed(2), exchange);
            if (res.success) successCount++;
            buyMsg += res.success
              ? `  \u2705 ${s.symbol} ${qty}\uc8fc \u00d7 $${s.price.toFixed(2)} \ub9e4\uc218 \uc8fc\ubb38 \uc811\uc218\n`
              : `  \u274c ${s.symbol} \ub9e4\uc218 \uc2e4\ud328: ${res.error}\n`;
          }
          buyMsg += "\n";
        }
      }
    }

    // 표시: 매수 먼저, 매도 나중에
    msg += buyMsg + sellMsg;

    // ★ 성공한 종목만 체결 확인 대상 (실패한 주문은 추적 불필요)
    const orderedSymbols = [];
    // msg에서 ✅ 포함된 종목만 추출
    const allStocks = [...sellStocks, ...buyStocks];
    for (const s of allStocks) {
      if (msg.includes(`✅ ${s.symbol}`)) {
        orderedSymbols.push(s.symbol);
      }
    }

    return { msg, orderedSymbols, successCount };
  } catch (e) {
    return "\u26a0\ufe0f \uc2b9\uc778 \ucc98\ub9ac \uc5d0\ub7ec: " + e.message;
  }
}

async function handleApproval(env) {
  if (isMarketOpen()) {
    // Market open -> execute immediately
    const result = await executeApproval(env);
    if (typeof result === "string") return result;
    if (result.successCount > 0) {
      // 1건이라도 성공 → 체결 확인 대상 저장
      await saveFillCheckToKV(env, result.orderedSymbols);
      return result.msg;
    } else {
      // 전부 실패 → KV에 저장하여 5분 뒤 cron 재시도
      if (env.KV) {
        await env.KV.put("pending_approval", JSON.stringify({
          type: "approval",
          requested_at: new Date().toISOString(),
          retry_count: 1,
        }));
      }
      return result.msg + "\n\n\u26a0\ufe0f \uc804\ubd80 \uc2e4\ud328. 5\ubd84 \ud6c4 \uc790\ub3d9 \uc7ac\uc2dc\ub3c4\ud569\ub2c8\ub2e4.";
    }
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
        if (qty <= 0) return sum;
        // ★ ovrs_stck_evlu_amt(해외주식평가금액)를 우선 사용 (KIS가 계산한 정확한 값)
        const evalAmt = parseFloat(h.ovrs_stck_evlu_amt || "0");
        if (evalAmt > 0) return sum + evalAmt;
        // fallback: now_pric2 * qty (장 외 시간 등 부정확할 수 있음)
        return sum + parseFloat(h.now_pric2 || "0") * qty;
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

// NYSE/NASDAQ 공식 휴장일 (verified)
// 2026: New Year, MLK, Presidents, Good Friday(4/3), Memorial, Juneteenth, Independence(observed), Labor, Thanksgiving, Christmas
// 2027: New Year, MLK, Presidents, Good Friday(3/26), Memorial, Juneteenth(observed), Independence(observed), Labor, Thanksgiving, Christmas(observed)
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
  // US Eastern Time 기준으로 요일/날짜 판단 (UTC가 아님!)
  try {
    const etDate = dateObj.toLocaleDateString("en-CA", { timeZone: "America/New_York" }); // yyyy-mm-dd
    const etDay = new Date(etDate + "T12:00:00").getDay(); // 0=일, 6=토
    if (etDay === 0 || etDay === 6) return false;
    if (US_HOLIDAYS.includes(etDate)) return false;
    return true;
  } catch {
    // Intl 미지원 폴백: UTC 기준 (기존 로직)
    const utcDay = dateObj.getUTCDay();
    if (utcDay === 0 || utcDay === 6) return false;
    const ymd = dateObj.toISOString().split("T")[0];
    if (US_HOLIDAYS.includes(ymd)) return false;
    return true;
  }
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
    const result = await executeEmergencySell(env);
    if (!result.allFailed) {
      return result.msg;
    } else {
      // 전부 실패 → KV에 저장하여 5분 뒤 cron 재시도
      if (env.KV) {
        await env.KV.put("pending_sell", JSON.stringify({
          type: "sell_all",
          requested_at: new Date().toISOString(),
          retry_count: 1,
        }));
      }
      return result.msg + "\n\n\u26a0\ufe0f \uc804\ubd80 \uc2e4\ud328. 5\ubd84 \ud6c4 \uc790\ub3d9 \uc7ac\uc2dc\ub3c4\ud569\ub2c8\ub2e4.";
    }
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
      return { msg: "\ud83d\udced \ubcf4\uc720 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc774\ubbf8 \ud604\uae08 100% \uc0c1\ud0dc\uc785\ub2c8\ub2e4.", allFailed: false };

    const active = holdings.filter(h => parseInt(h.ovrs_cblc_qty || "0") > 0);
    if (active.length === 0) return { msg: "\ud83d\udced \ubcf4\uc720 \uc885\ubaa9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.", allFailed: false };

    let msg = "\ud83d\uded1 *[\uc804\ub7c9 \ub9e4\ub3c4 \uc2e4\ud589]*\n\n";
    let sellOk = 0;
    for (const h of active) {
      const sym = h.ovrs_pdno || "?";
      const qty = parseInt(h.ovrs_cblc_qty || "0");
      const cur = parseFloat(h.now_pric2 || "0");
      const sellPrice = (cur * 0.995).toFixed(2);

      // 거래소 자동 감지 후 매도
      const exchange = await detectExchange(env, sym);
      const res = await sellOrder(env, sym, qty, sellPrice, exchange);
      if (res.success) sellOk++;
      const status = res.success ? "\u2705 \uc644\ub8cc" : "\u274c \uc2e4\ud328";
      msg += "  " + status + " *" + sym + "* " + qty + "\uc8fc \u00d7 $" + sellPrice + "\n";
    }
    msg += "\n\ud83d\udee1\ufe0f \ub9e4\ub3c4 \ucc98\ub9ac\uac00 \uc644\ub8cc\ub418\uc5c8\uc2b5\ub2c8\ub2e4, \ub300\ud45c\ub2d8.";
    return { msg, allFailed: sellOk === 0 && active.length > 0 };
  } catch (e) {
    return { msg: "\u26a0\ufe0f \ub9e4\ub3c4 \uc5d0\ub7ec: " + e.message, allFailed: true };
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
        body: JSON.stringify({ ref: "main", inputs: { force_rescan: "true", force_send: "true" } }),
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

  // Reference indicators (참고 지표)
  if (text === "\uc9c0\ud45c") {
    if (!env.GITHUB_PAT) {
      await sendMessage(env, "\u26a0\ufe0f GitHub \uc5f0\ub3d9\uc774 \uc124\uc815\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.", REPLY_KEYBOARD);
      return;
    }
    try {
      const r = await fetch("https://api.github.com/repos/abraxass0511-lab/Alpha-Investment-Agent/actions/workflows/alpha_indicators.yml/dispatches", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GITHUB_PAT}`,
          "Accept": "application/vnd.github+json",
          "User-Agent": "Alpha-Bot",
        },
        body: JSON.stringify({ ref: "main" }),
      });
      if (r.ok || r.status === 204) {
        await sendMessage(env, "\ud83d\udce1 *\ucc38\uace0 \uc9c0\ud45c \uc870\ud68c \uc2dc\uc791!*\n\n\uc57d 2~3\ubd84 \ud6c4 \ubc84\ud54f\uc9c0\ud45c\u00b7QQQ \ud558\ub77d\ub960\u00b7\uacf5\ud3ec\u00b7\ud0d0\uc695 \uc9c0\uc218\ub97c \uc54c\ub824\ub4dc\ub9ac\uaca0\uc2b5\ub2c8\ub2e4, \ub300\ud45c\ub2d8.", REPLY_KEYBOARD);
      } else {
        await sendMessage(env, "\u26a0\ufe0f *GitHub \uc11c\ubc84 \ubb38\uc81c*\n\n\uc9c0\ud45c \uc694\uccad\uc744 GitHub\uc5d0 \uc804\ub2ec\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.\nHTTP " + r.status + "\n\n\uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.", REPLY_KEYBOARD);
      }
    } catch (e) {
      await sendMessage(env, "\u26a0\ufe0f *GitHub \uc811\uc18d \uc2e4\ud328*\n\n\uc9c0\ud45c \uc870\ud68c \uc694\uccad\uc744 \uc804\ub2ec\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.\n\uc624\ub958: " + (e.message || "Unknown") + "\n\n\uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.", REPLY_KEYBOARD);
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

  if (text === "\ubc18\ub824") {
    const response = await handleReject(env);
    await sendMessage(env, response, REPLY_KEYBOARD);
    return;
  }

  const response = await handleAiChat(env, text);
  await sendMessage(env, response, REPLY_KEYBOARD);
}
