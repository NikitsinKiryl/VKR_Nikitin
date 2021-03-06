from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.contrib import layers
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import rnn
from tensorflow.python.ops import tensor_array_ops
from tensorflow.python.ops import variable_scope as vs

__all__ = ["dynamic_rnn_decoder"]

def dynamic_rnn_decoder(cell, decoder_fn, inputs=None, sequence_length=None,
                                                parallel_iterations=None, swap_memory=False,
                                                time_major=False, scope=None, name=None):
    with ops.name_scope(name, "dynamic_rnn_decoder",
                                            [cell, decoder_fn, inputs, sequence_length,
                                             parallel_iterations, swap_memory, time_major, scope]):
        if inputs is not None:
            # Convert to tensor
            inputs = ops.convert_to_tensor(inputs)

            # Test input dimensions
            if inputs.get_shape().ndims is not None and (
                    inputs.get_shape().ndims < 2):
                raise ValueError("Inputs must have at least two dimensions")
            # Setup of RNN (dimensions, sizes, length, initial state, dtype)
            if not time_major:
                # [batch, seq, features] -> [seq, batch, features]
                inputs = array_ops.transpose(inputs, perm=[1, 0, 2])

            dtype = inputs.dtype
            # Get data input information
            input_depth = int(inputs.get_shape()[2])
            batch_depth = inputs.get_shape()[1].value
            max_time = inputs.get_shape()[0].value
            if max_time is None:
                max_time = array_ops.shape(inputs)[0]
            # Setup decoder inputs as TensorArray
            inputs_ta = tensor_array_ops.TensorArray(dtype, size=max_time)
            inputs_ta = inputs_ta.unstack(inputs)

        def loop_fn(time, cell_output, cell_state, loop_state):
            if cell_state is None:    # first call, before while loop (in raw_rnn)
                if cell_output is not None:
                    raise ValueError("Expected cell_output to be None when cell_state "
                                                     "is None, but saw: %s" % cell_output)
                if loop_state is not None:
                    raise ValueError("Expected loop_state to be None when cell_state "
                                                     "is None, but saw: %s" % loop_state)
                context_state = None
            else:    # subsequent calls, inside while loop, after cell excution
                if isinstance(loop_state, tuple):
                    (done, context_state) = loop_state
                else:
                    done = loop_state
                    context_state = None

            # call decoder function
            if inputs is not None:    # training
                # get next_cell_input
                if cell_state is None:
                    next_cell_input = inputs_ta.read(0)
                else:
                    if batch_depth is not None:
                        batch_size = batch_depth
                    else:
                        batch_size = array_ops.shape(done)[0]
                    next_cell_input = control_flow_ops.cond(
                            math_ops.equal(time, max_time),
                            lambda: array_ops.zeros([batch_size, input_depth], dtype=dtype),
                            lambda: inputs_ta.read(time))
                (next_done, next_cell_state, next_cell_input, emit_output,
                 next_context_state) = decoder_fn(time, cell_state, next_cell_input,
                                                                                    cell_output, context_state)
            else:    # inference
                # next_cell_input is obtained through decoder_fn
                (next_done, next_cell_state, next_cell_input, emit_output,
                 next_context_state) = decoder_fn(time, cell_state, None, cell_output,
                                                                                    context_state)

            # check if we are done
            if next_done is None:    # training
                next_done = time >= sequence_length

            # build next_loop_state
            if next_context_state is None:
                next_loop_state = next_done
            else:
                next_loop_state = (next_done, next_context_state)

            return (next_done, next_cell_input, next_cell_state,
                            emit_output, next_loop_state)

        # Run raw_rnn function
        outputs_ta, final_state, final_loop_state = rnn.raw_rnn(
                cell, loop_fn, parallel_iterations=parallel_iterations,
                swap_memory=swap_memory, scope=scope)
        outputs = outputs_ta.stack()

        # Get final context_state, if generated by user
        if isinstance(final_loop_state, tuple):
            final_context_state = final_loop_state[1]
        else:
            final_context_state = None

        if not time_major:
            # [seq, batch, features] -> [batch, seq, features]
            outputs = array_ops.transpose(outputs, perm=[1, 0, 2])
        return outputs, final_state, final_context_state
