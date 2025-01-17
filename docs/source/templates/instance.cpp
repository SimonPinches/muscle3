#include <cstdlib>
#include <vector>

#include <libmuscle/libmuscle.hpp>
#include <ymmsl/ymmsl.hpp>


using libmuscle::Instance;
using libmuscle::Message;
using ymmsl::Operator;


/**
 * MUSCLE3 C++ component template.
 *
 * Note that this template is not executable as is, please have a look at the
 * examples in ``docs/source/examples`` to see working components.
 */
int main(int argc, char * argv[]) {
    Instance instance(argc, argv, {
            {Operator::F_INIT, {"F_INIT_Port"}},
            {Operator::O_I, {"O_I_Port"}},
            {Operator::S, {"O_S_Port"}},
            {Operator::O_F, {"O_F_Port"}}});

    while (instance.reuse_instance()) {
        // F_INIT
        auto setting = instance.get_setting("setting");
        // ...

        instance.receive("F_INIT_Port");
        // ...

        while (t_cur <= t_max) {
            // O_I
            Message msg(t_cur, data);
            if(t_cur + dt <= t_max)
                msg.set_next_timestamp(t_cur + dt);
            instance.send("O_I_Port", msg);
            // ...

            // S
            instance.receive("S_Port");
            // ...

            t_cur += dt;
        }

        // O_F
        instance.send("final_state", Message(t_cur, data));
    }

    return EXIT_SUCCESS;
}

