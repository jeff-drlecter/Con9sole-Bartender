# bot.py 內
import pkgutil
import importlib
import traceback
import os

async def setup_cogs():
    # 1) 確保 cogs 係一個 package（有 __init__.py）
    import cogs  # noqa

    # 2) 用 cogs.__path__ 掃描（比傳入 'cogs' 字串可靠）
    found = list(pkgutil.iter_modules(cogs.__path__))

    print("📁 cogs/ 目錄實際檔案：", os.listdir("cogs"))
    print("🔎 掃到模組：", [name for _, name, _ in found])

    # 3) 自動載入所有頂層 .py（排除底線開頭，例如 __init__.py）
    loaded_any = False
    for _, name, ispkg in found:
        if name.startswith("_"):
            continue
        mod = f"cogs.{name}"
        try:
            await bot.load_extension(mod)
            print(f"🔌 Loaded {mod}")
            loaded_any = True
        except Exception:
            print(f"❌ Load {mod} 失敗：")
            traceback.print_exc()

    if not loaded_any:
        print("⚠️ 未載入到任何 cog，請檢查 .dockerignore / 路徑 / 語法。")
