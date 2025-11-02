#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include <deque>
#include <unordered_map>

namespace va { namespace analyzer { namespace multistage {

class NodeReidSmooth : public INode {
public:
    explicit NodeReidSmooth(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_key_}; }
    std::vector<std::string> outputs() const override { return {out_key_}; }

private:
    enum class Method { EMA, MEAN };
    struct MeanState {
        std::deque<std::vector<float>> window;
        std::vector<float> sum; // sum over window
    };
    struct EmaState {
        std::vector<float> value; // smoothed value
        bool initialized {false};
    };
    struct State {
        MeanState mean;
        EmaState ema;
    };

    std::string in_key_ {"tensor:reid"};
    std::string out_key_ {"tensor:reid_smooth"};
    std::string id_attr_ {"track_id"};
    Method method_ {Method::EMA};
    int window_ {10};
    float decay_ {0.9f}; // EMA decay for previous value
    bool l2norm_ {true};
    bool passthrough_if_missing_ {true};
    std::vector<float> out_buffer_;

    std::unordered_map<std::string, State> cache_;

    static std::string attr_to_id(const Attr& a);
    static void l2_normalize(std::vector<float>& v);
};

} } } // namespace
