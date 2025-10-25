#include "lro/state_store.h"

namespace lro {

std::shared_ptr<IStateStore> make_memory_store() {
    return std::make_shared<MemoryStore>();
}

} // namespace lro

