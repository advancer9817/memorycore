import sys
sys.path.insert(0, "/home/advancer/project/memorycore")
import memorycore.storage.search as search
try:
    search.build_context_pack("hello")
except Exception as e:
    import traceback
    traceback.print_exc()
