# 璁剧疆椤甸厤缃府鍔╃淮鎶よ鏄?

璁剧疆椤甸厤缃府鍔╃敤浜庢妸閰嶇疆椤圭殑鍏抽敭璇存槑鏀惧埌 WebUI 鍐呴儴锛屽噺灏戠敤鎴峰湪璁剧疆椤靛拰鏂囨。涔嬮棿鍙嶅鍒囨崲銆傞〉闈笂浠嶄繚鐣欑煭鎻忚堪锛岃缁嗚鏄庨€氳繃閰嶇疆椤规爣棰樻梺鐨?help icon 鎵撳紑銆?

鏈枃鍙鏄庡府鍔╃郴缁熺殑缁存姢瑙勫垯锛屼笉鏇夸唬瀹屾暣閰嶇疆鏂囨。銆傞厤缃涔夈€侀粯璁ゅ€笺€佽繍琛屾椂浼樺厛绾у拰鎺掗殰缁嗚妭浠嶄互 `.env.example`銆乣docs/full-guide.md` 鍙婂搴斾笓棰樻枃妗ｄ负浜嬪疄婧愩€?

## 鏁版嵁缁撴瀯

鍚庣閰嶇疆娉ㄥ唽琛ㄥ湪 `src/core/config_registry.py` 涓负瀛楁杩藉姞甯姪鍏冩暟鎹細

- `help_key`锛氬墠绔璇█甯姪鏂囨鐨勭ǔ瀹?key銆?
- `examples`锛氬彲鐩存帴灞曠ず鐨勯厤缃牱渚嬨€傛晱鎰熷瓧娈靛彧鑳戒娇鐢ㄥ崰浣嶇锛屼緥濡?`sk-xxxx`銆乣your_token`銆?
- `docs`锛氱浉鍏虫枃妗ｉ摼鎺ワ紝浼樺厛鎸囧悜浠撳簱鍐呭凡鏈変笓棰樻枃妗ｆ垨瀹屾暣鎸囧崡銆?
- `warning_codes`锛氶潰鍚戝墠绔垨鍚庣画鏍￠獙鎵╁睍鐨勭ǔ瀹氭彁绀?code銆?

鍓嶇闀挎枃妗堢淮鎶ゅ湪 `apps/dsa-web/src/locales/settingsHelp.ts`锛?

- 榛樿灞曠ず涓枃鏂囨銆?
- 鑻辨枃鏂囨淇濈暀鍚屾牱缁撴瀯锛屼究浜庡悗缁墿灞曡瑷€鍒囨崲銆?
- 鏂囨搴旇В閲婄敤閫斻€佸彇鍊艰鏄庛€佸奖鍝嶈寖鍥淬€佹敞鎰忎簨椤瑰拰鐩稿叧鏂囨。锛屼笉搴斿鍒跺畬鏁翠笓棰樻枃妗ｃ€?

## WebUI 璇█璇存槑锛堥潪閰嶇疆椤癸級

鏈」鐩柊澧炵嫭绔嬬殑 WebUI 鐣岄潰璇█鑳藉姏锛坄zh` / `en`锛夛紝鐢ㄤ簬闈欐€侀〉闈㈡枃妗堛€佸鑸笌閫氱敤鎺т欢鏂囨銆傝鐘舵€佷笌 `REPORT_LANGUAGE` 瑙ｈ€︼紝涓嶆敼鍐欐姤鍛婅瑷€璇箟銆?

- 鐘舵€侀敭锛歚dsa.uiLanguage`锛坄localStorage`锛屾祻瑙堝櫒绔寔涔呭寲锛夈€?
- 鍒濆鍖栦紭鍏堢骇锛歚localStorage` 鏈夋晥鍊间紭鍏堬紝鍏舵璇嗗埆娴忚鍣ㄨ瑷€锛坄zh-*` / `en-*`锛夛紝鏈€鍚庡洖閫€ `zh`銆?
- 璇ヨ瑷€寮€鍏充笉灞炰簬 `.env` 閰嶇疆瀛楁锛屼笉鍦?`system/config` 鐨勫彲閰嶇疆瀛楁娓呭崟涓綋鐜般€?
- 鐣岄潰鍒囨崲浼氬悓姝?`document.documentElement.lang`锛坄zh-CN` 鎴?`en`锛変互鍒╀簬鍙闂€т笌鏃犻殰纰嶈涔夈€?

## 瑕嗙洊鑼冨洿

PR1 瑕嗙洊鍩虹璁炬柦涓庨鎵逛唬琛ㄦ€ч厤缃」锛?

- `STOCK_LIST`
- `LITELLM_MODEL`
- `LLM_CHANNELS`
- `FEISHU_WEBHOOK_URL`
- `WEBUI_HOST`

PR2 缁х画瑕嗙洊楂橀銆佹槗濉敊閰嶇疆椤癸細

- AI 妯″瀷杩愯鏃讹細Agent 涓绘ā鍨嬨€乫allback 妯″瀷銆侀珮绾?YAML 璺敱銆乼emperature銆乸rovider API Key銆丱penAI-compatible Base URL銆?
- LLM Channels 缂栬緫鍣ㄥ唴閮ㄥ瓧娈碉細娓犻亾鍚嶃€佸崗璁€丅ase URL銆丄PI Key銆佹ā鍨嬪垪琛ㄣ€佽繍琛屾椂鑳藉姏妫€娴嬨€佷富妯″瀷銆丄gent 涓绘ā鍨嬨€乫allback銆乂ision 鍜?temperature銆?
- 鏁版嵁婧愪笌鎼滅储锛歍ushare銆佽偂绁ㄧ储寮曡繙绋嬫洿鏂板紑鍏炽€佸疄鏃惰鎯呬紭鍏堢骇銆佸疄鏃舵妧鏈寚鏍囥€佹悳绱?API Key銆丼earXNG銆佺鐮佸垎甯冦€佹柊闂荤獥鍙ｃ€?
- 閫氱煡锛歐ebhook銆乀elegram銆侀偖浠躲€丏iscord/Slack 绛夎亰澶╁钩鍙般€佹姤鍛婅緭鍑恒€乄ebhook SSL 鏍￠獙銆?
- WebUI / auth / schedule / proxy锛欻ost銆丳ort銆佺櫥褰曚繚鎶ゃ€佸彲淇″弽鍚戜唬鐞嗐€佸畾鏃朵换鍔°€佷氦鏄撴棩妫€鏌ャ€佺綉缁滀唬鐞嗐€?

PR3 registered-field slice / 闃舵鎬цˉ榻愶細鑱氱劍 Web 璁剧疆椤典腑瀹為檯灞曠ず/鍙厤缃瓧娈电殑 Help 琛ラ綈锛屽寘鎷€氱敤閰嶇疆鍗＄墖褰撳墠鍙瀛楁鍜?AI legacy 鏉′欢鍙瀛楁锛?

- Agent 閰嶇疆锛?1 瀛楁锛夛細Agent 妯″紡銆佹渶澶ф帹鐞嗘鏁般€佺瓥鐣ュ垪琛ㄣ€佺瓥鐣ョ洰褰曘€佽嚜鐒惰瑷€璺敱銆佹灦鏋勩€佺紪鎺掑櫒妯″紡銆佽秴鏃躲€侀闄╁惁鍐炽€丏eep Research 棰勭畻/瓒呮椂銆佽蹇嗐€佺瓥鐣ヨ嚜鍔ㄦ潈閲嶃€佺瓥鐣ヨ矾鐢便€侀棶鑲″彲瑙佸璇濅笂涓嬫枃鍘嬬缉銆佷簨浠剁洃鎺у紑鍏?闂撮殧銆佸憡璀﹁鍒?JSON銆?
- 鍥炴祴閰嶇疆锛? 瀛楁锛夛細鍥炴祴寮€鍏炽€佽瘎浼扮獥鍙ｃ€佹渶灏忚褰曞勾榫勩€佸紩鎿庣増鏈€佷腑鎬у洖鎶ュ甫銆?
- 鎶ュ憡閰嶇疆锛? 瀛楁锛夛細浠呮帹閫佹憳瑕併€佹樉绀烘ā鍨嬪悕銆佹ā鏉跨洰褰曘€佹覆鏌撳紩鎿庛€佸畬鏁存€ф牎楠?閲嶈瘯銆佸巻鍙蹭俊鍙峰姣斻€侀€愯偂鎺ㄩ€併€佸悎骞堕偖浠躲€?
- 閫氱煡璺敱閰嶇疆锛? 瀛楁锛夛細鎶ュ憡/鍛婅/绯荤粺閿欒娓犻亾璺敱銆佸幓閲?鍐峰嵈銆侀潤榛樻椂娈?鏃跺尯銆佹渶浣庣瓑绾с€佹瘡鏃ユ憳瑕侊紙棰勭暀锛夈€?
- 绯荤粺杩愯鏃讹紙7 瀛楁锛夛細鏃ュ織绾у埆銆佽皟璇曟ā寮忋€佹渶澶у苟鍙戙€佸垎鏋愰棿闅斻€佸ぇ鐩樺垎鏋愬紑鍏?甯傚満/閰嶈壊銆?
- AI legacy 涓?Anspire 閰嶇疆锛歱rovider 涓撶敤澶?Key銆佹ā鍨嬪悕銆佹俯搴︺€乂ision 妯″瀷銆乵ax tokens 涓?Anspire LLM 缃戝叧瀛楁銆?
- 鏁版嵁婧愪笌鎼滅储锛歍ickFlow銆丼erpAPI銆丅rave銆丅ocha銆丮iniMax銆丼earXNG 鍏叡瀹炰緥銆丅IAS 闃堝€煎拰 Pytdx 鏈嶅姟鍣ㄥ瓧娈点€?
- 閫氱煡楂樼骇瀛楁锛氶涔﹂珮绾у畨鍏?搴旂敤瀛楁銆乀elegram topic銆丏iscord/Slack 楂樼骇瀛楁銆丳ushover銆乶tfy銆丟otify銆丳ushPlus銆丼erverChan3銆丄strBot 鍜岃嚜瀹氫箟 Webhook 楂樼骇妯℃澘/閴存潈瀛楁銆?

- 数据源与搜索：内置 360 新闻直连搜索、TickFlow、SerpAPI、Brave、Bocha、MiniMax、SearXNG 公共实例、BIAS 阈值和 Pytdx 服务器字段。
Issue #1512 鏀跺彛鍚庯紝Web 璁剧疆椤靛彧灞曠ず鍚庣閰嶇疆娉ㄥ唽琛ㄤ腑鐨勬寮忓瓧娈点€傛湭娉ㄥ唽鐨?`.env` key 涓嶅啀浣滀负鏅€氬彲缂栬緫璁剧疆椤瑰睍绀猴紝閬垮厤 raw key銆乣Auto-inferred field metadata.` 鍜屾棤 help 鎸夐挳鐨勯厤缃」杩涘叆涓枃鐣岄潰锛涜繖浜?key 浠嶅彲閫氳繃 `.env` 鏂囦欢鎴栧鍏?瀵煎嚭鑳藉姏淇濈暀鍜岀淮鎶ゃ€?

渚嬪锛歚LLM_CHANNELS` 澹版槑鐨勫姩鎬佹笭閬撹鎯呴敭锛堝 `LLM_DEEPSEEK_API_KEY`銆乣LLM_MY_PROXY_MODELS`锛変細淇濈暀鍦ㄩ厤缃帴鍙ｈ繑鍥炰腑锛屼緵鈥淎I 妯″瀷鎺ュ叆鈥濈紪杈戝櫒璇诲彇鍜屼繚瀛橈紱瀹冧滑涓嶄綔涓烘櫘閫氶厤缃崱鐗囧睍绀猴紝涔熶笉澶嶇敤 `WEB_SETTINGS_HIDDEN_FROM_UI` 鐨勮繍缁撮殣钘忚涔夈€?

鏆備笉绾冲叆 Web 璁剧疆椤靛睍绀虹殑浣庨/杩愮淮绫?`.env` 鍙橀噺鍖呮嫭 `DATABASE_PATH`銆乣SQLITE_*`銆乣USE_PROXY`銆乣PROXY_HOST`銆乣PROXY_PORT` 绛夈€傝嫢鍚庣画闇€瑕佸湪 Web 涓紪杈戣繖浜涘瓧娈碉紝搴斿厛鍦?`src/core/config_registry.py` 涓寮忔敞鍐屽苟琛ラ綈 help 鍏冩暟鎹紝鑰屼笉鏄緷璧栬嚜鍔ㄦ帹鏂€?

### 瑕嗙洊杈圭晫

- `settingsHelp.ts` 涓殑 `settings.llm_channel.*` 绯诲垪涓?LLM 娓犻亾缂栬緫鍣ㄥ唴閮ㄥ瓧娈佃鏄庯紝浠呯敤浜庡墠绔覆鏌擄紝涓嶅搴?`.env` 鐨勫崟鐙厤缃」锛涜繖鏄?PR2 涓埢鎰忕殑鈥滃唴缃墿灞曗€濊璁★紝鐢ㄤ簬鎻愬崌缂栬緫鍣ㄥ彲鐢ㄦ€с€?
- 鍏朵綑 help 鏂囨鍧囧簲鑳戒粠 `src/core/config_registry.py` 涓煇涓瓧娈电殑 `help_key` 鏄犲皠鍒板悗绔敞鍐屽厓鏁版嵁锛屼究浜庝笌鏂囨。婧愩€乣warning_codes` 涓€璧风粺涓€缁存姢銆?

## 浜嬪疄婧愪紭鍏堢骇

鏂板鎴栦慨鏀瑰府鍔╂枃妗堟椂锛屼紭鍏堜粠浠ヤ笅浣嶇疆鏍稿锛?

1. `.env.example`锛氶厤缃敭鍚嶃€侀粯璁ゅ€笺€佹牱渚嬫牸寮忓拰鏁忔劅鍗犱綅绗︺€?
2. `docs/full-guide.md`锛氫富瑕侀厤缃鏄庛€佽繍琛屽叆鍙ｅ拰閮ㄧ讲涓婁笅鏂囥€?
3. `docs/LLM_CONFIG_GUIDE.md`銆乣docs/llm-providers.md`锛歀LM 浼樺厛绾с€丆hannels銆乸rovider/model銆佸吋瀹硅竟鐣屽拰鎺掗殰璇存槑銆?
4. 涓撻鏂囨。锛氫緥濡?`docs/bot/feishu-bot-config.md`銆乣docs/deploy-webui-cloud.md`銆乣docs/desktop-package.md`銆?
5. 浠ｇ爜瀹炵幇鍜屾祴璇曪細褰撴枃妗ｄ笌浠ｇ爜涓嶄竴鑷存椂锛屽厛浠ュ彲鎵ц瀹炵幇涓哄噯锛屽苟鍚屾淇鏂囨。銆?

## 缁存姢杈圭晫

- 甯姪鏂囨涓嶈兘鏀瑰彉閰嶇疆淇濆瓨銆佹牎楠屻€佽繍琛屾椂浼樺厛绾с€乣.env` 鍐欏洖鎴栫幆澧冨彉閲忚鐩栬涔夈€?
- 涓嶅睍绀虹湡瀹炲瘑閽ャ€佽处鍙枫€乼oken銆乄ebhook 瀹屾暣鍊兼垨鏈満缁濆璺緞銆?
- LLM 鐩稿叧绀轰緥濡傛灉鍐欏叆鍏蜂綋 provider 鍓嶇紑銆佹ā鍨嬪悕鎴?Base URL锛屽繀椤昏兘杩芥函鍒板綋鍓嶄粨搴撴枃妗ｆ垨瀹樻柟鏉ユ簮锛涘惁鍒欏簲浣跨敤鍗犱綅绗︽垨閾炬帴鍒颁簨瀹炴簮銆?
- 瀵圭涓夋柟妯″瀷/API 鐨勫彲鐢ㄦ€с€丩iteLLM 鍏煎绐楀彛鎴?provider fallback 瑙勫垯锛屼笉鍦ㄨ缃府鍔╀腑鍗曠嫭鎵胯锛涢渶瑕佸彉鏇存椂蹇呴』鍚屾鏇存柊涓撻鏂囨。鍜?PR 鍏煎鎬ц鏄庛€?
- 涓嫳鍙岃鏂囨搴斾繚鎸佸悓涓€璇箟鑼冨洿銆傝嫢鍙洿鏂颁竴绉嶈瑷€锛岄渶瑕佸湪浜や粯璇存槑涓啓鏄庡師鍥犮€?
- 棣栧睆鐭弿杩颁繚鎸佺畝娲侊紝璇︾粏璇存槑鏀惧湪 help dialog 涓紝閬垮厤 hover tooltip 涓庡父椹荤煭鎻忚堪閲嶅銆?

## 閲嶅惎璇箟

璁剧疆椤典繚瀛橀€氬父鍙啓鍏?`.env` 骞惰Е鍙戝彲杩愯鏃堕噸杞界殑閰嶇疆鍒锋柊銆傚府鍔╂枃妗堝拰 `warning_codes` 蹇呴』鏄惧紡鍖哄垎浠ヤ笅鎯呭喌锛?

- `WEBUI_HOST`銆乣WEBUI_PORT`锛氱洃鍚湴鍧€鍜岀鍙ｅ彧鍦ㄨ繘绋嬪惎鍔ㄦ椂缁戝畾锛屼繚瀛樺悗蹇呴』閲嶅惎褰撳墠杩涚▼銆丏ocker 瀹瑰櫒鎴栨湇鍔＄鐞嗗櫒鎵嶄細鐢熸晥銆?
- `RUN_IMMEDIATELY`锛氶潪 schedule 妯″紡鍚姩鏈熷崟娆¤繍琛岄厤缃紝淇濆瓨鍚庝笉浼氳宸茶繍琛岀殑 WebUI/API 杩涚▼绔嬪嵆瑙﹀彂鍒嗘瀽銆?
- Web 璁剧疆椤典笉鐩存帴鏆撮湶 `SCHEDULE_TIME` / `SCHEDULE_TIMES` / `SCHEDULE_RUN_IMMEDIATELY` 绛夊唴閮ㄩ敭锛涚敤鎴烽€氳繃鈥滃畾鏃朵换鍔♀€濆崱鐗囩淮鎶ゅ惎鐢ㄧ姸鎬併€佸涓墽琛屾椂闂村拰绔嬪嵆鎵ц涓€娆°€?
- `SCHEDULE_ENABLED`锛歐ebUI/API/Desktop 闀胯繍琛岃繘绋嬶紙鍖呮嫭 `python main.py --serve --schedule`锛変細鍦ㄤ繚瀛樺悗鎸夋柊鍊煎惎鍔ㄦ垨鍋滄 runtime scheduler锛涚函 CLI schedule 妯″紡锛坄python main.py --schedule`锛変粛鎸夊惎鍔ㄦ椂鍙傛暟鍜岄厤缃繍琛屻€?
- `SCHEDULE_TIME`銆乣SCHEDULE_TIMES`锛氫笉鏄噸鍚繀闇€椤广€俙SCHEDULE_TIMES` 涓虹┖鏃朵娇鐢?`SCHEDULE_TIME`锛涘凡杩愯鐨?scheduler 浼氭寜鏂版椂闂撮噸寤?daily jobs銆?
- `SCHEDULE_RUN_IMMEDIATELY`锛歴chedule 妯″紡鍚姩琛屼负锛屼繚瀛樺悗涓嶄細璁╁綋鍓嶈繘绋嬬珛鍗虫墽琛屼竴娆″垎鏋愶紱鎵嬪姩鎵ц璇蜂娇鐢?runtime scheduler 鐨?run-now API銆?
- runtime scheduler 鐨?run-now API 鍙細鍦ㄦ病鏈夊垎鏋愪换鍔¤繍琛屾椂鎺ュ彈璇锋眰锛涘鏋滃凡鏈夊垎鏋愬湪鎵ц锛屼細杩斿洖蹇欑鐘舵€侊紝Web 璁剧疆椤典細鎻愮ず绋嶅悗閲嶈瘯銆?
