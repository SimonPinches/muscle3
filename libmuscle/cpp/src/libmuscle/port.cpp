#include "libmuscle/port.hpp"

#include <stdexcept>
#include <string>

#include <ymmsl/ymmsl.hpp>


using namespace std::string_literals;
using ymmsl::Identifier;
using ymmsl::Operator;


namespace {

template< typename T>
inline void extend_vector_to_size(
        std::vector<T> &vec, const int minsize, const T &val) {
    if(static_cast<int>(vec.size()) < minsize) {
        vec.resize(minsize, val);
    }
}

}


namespace libmuscle { namespace impl {

Port::Port(
        std::string const & name, Operator oper,
        bool is_vector, bool is_connected,
        int our_ndims, std::vector<int> peer_dims)
    : ::ymmsl::Port(Identifier(name), oper)
{
    is_connected_ = is_connected;
    if (is_vector) {
        if (our_ndims == static_cast<int>(peer_dims.size()))
            length_ = 0;
        else if ((our_ndims + 1) == static_cast<int>(peer_dims.size()))
            length_ = peer_dims.back();
        else if (our_ndims > static_cast<int>(peer_dims.size()))
            throw std::runtime_error("Vector port '"s + name + "' is connected"
                    + " to an instance set with fewer dimensions. It should be"
                    + " connected to a scalar port on a set with one more"
                    + " dimension, or to a vector port on a set with the same"
                    + " number of dimensions.");
        else
            throw std::runtime_error("Port '"s + name + "' is connected to an"
                    + " instance set with more than one dimension more than"
                    + " its own, which is not possible.");
        is_open_ = std::vector<bool>(length_, true);
    }
    else {
        if (our_ndims < static_cast<int>(peer_dims.size()))
            throw std::runtime_error("Scalar port "s + name + " is connected"
                    + " to an instance set with more dimensions. It should be"
                    + " connected to a scalar port on an instance set with the"
                    + " same dimensions, or to a vector port on an instance"
                    + " set with with one less dimension.");
        else if (our_ndims > static_cast<int>(peer_dims.size()) + 1)
            throw std::runtime_error("Scalar port "s + name + " is connected"
                    + " to an instance set with at least two fewer dimensions,"
                    + " which is not possible.");
        length_ = -1;
        is_open_.push_back(true);
    }

    is_resizable_ = is_vector && (our_ndims == static_cast<int>(peer_dims.size()));
    num_messages_.resize(std::max(1, length_), 0);
    is_resuming_.resize(std::max(1, length_), false);
}

bool Port::is_connected() const {
    return is_connected_;
}

bool Port::is_open() const {
    return is_open_.at(0u);
}

bool Port::is_open(int slot) const {
    return is_open_.at(slot);
}

bool Port::is_open(Optional<int> slot) const {
    if (slot.is_set())
        return is_open(slot.get());
    return is_open();
}

bool Port::is_vector() const {
    return length_ >= 0;
}

bool Port::is_resizable() const {
    return is_resizable_;
}

int Port::get_length() const {
    if (length_ < 0)
        throw std::runtime_error("Tried to get length of scalar port "s + name);
    return length_;
}

void Port::set_length(int length) {
    if (!is_resizable_)
        throw std::runtime_error("Tried to resize port "s + name + ", but it is"
                + " not resizable");
    if (length != length_) {
        length_ = length;
        is_open_ = std::vector<bool>(length_, true);
        // Using extend here to not discard any information about message
        // numbers between resizes. Note that _num_messages and _is_resuming
        // may be longer than self._length!
        extend_vector_to_size(num_messages_, std::max(1, length_), 0);
        extend_vector_to_size(is_resuming_, std::max(1, length_), false);
    }
}

void Port::set_closed() {
    is_open_[0] = false;
}

void Port::set_closed(int slot) {
    is_open_[slot] = false;
}

void Port::restore_message_counts(const std::vector<int> &num_messages) {
    num_messages_ = std::vector<int>(num_messages);
    is_resuming_.clear();
    is_resuming_.resize(num_messages_.size(), true);
    extend_vector_to_size(num_messages_, std::max(1, length_), 0);
    extend_vector_to_size(is_resuming_, std::max(1, length_), false);
}

const std::vector<int> & Port::get_message_counts() const {
    return num_messages_;
}

void Port::increment_num_messages(Optional<int> slot) {
    int s = slot.is_set() ? slot.get() : 0;
    num_messages_[s] ++;
    set_resumed(s);
}

int Port::get_num_messages(Optional<int> slot) const {
    int s = slot.is_set() ? slot.get() : 0;
    return num_messages_[s];
}

bool Port::is_resuming(Optional<int> slot) const {
    int s = slot.is_set() ? slot.get() : 0;
    return is_resuming_[s];
}

void Port::set_resumed(Optional<int> slot) {
    int s = slot.is_set() ? slot.get() : 0;
    is_resuming_[s] = false;
}

} }

