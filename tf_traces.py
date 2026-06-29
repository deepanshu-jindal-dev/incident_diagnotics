"""Realistic TensorFlow stack traces for the Incident Diagnostics Engine.

All ops-layer frames use actual function names and line numbers from ops_graph.pkl.
Upper frames (Keras, eager, framework) are realistic paths from a standard TF 2.x
installation — they are not in the graph but make the trace look like it came from
a real training session. The engine anchors on the ops-layer frames.

Five scenarios covering common production failure modes:

  TF_TRACE_1  Shape mismatch in flatten → reshape during forward pass
  TF_TRACE_2  NaN loss in sigmoid_cross_entropy_with_logits after logit overflow
  TF_TRACE_3  Gradient explosion — clip_by_global_norm receives Inf norm
  TF_TRACE_4  Assertion failure on label rank mismatch deep in data pipeline
  TF_TRACE_5  Out-of-bounds index in embedding_lookup after vocab truncation
"""

_OPS = "tensorflow/python/ops"

# ── Trace 1 ──────────────────────────────────────────────────────────────────
# A conv layer's output channels were changed from 256 to 512 but the
# downstream Dense layer's input_dim was not updated. The mismatch surfaces
# only at runtime when reshape() tries to flatten the batch for the dense layer.
# Upper stack: Keras training loop → model call → flatten layer → reshape.
# The error message names the tensor size but not which layer caused the change.
TF_TRACE_1 = f"""\
Traceback (most recent call last):
  File "train.py", line 94, in <module>
    history = model.fit(train_ds, epochs=20, validation_data=val_ds, callbacks=callbacks)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 1184, in fit
    tmp_logs = self.train_function(iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 853, in train_function
    return step_function(self, iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 842, in step_function
    outputs = model.distribute_strategy.run(run_step, args=(data,))
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 831, in run_step
    outputs = model.train_step(data)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 791, in train_step
    y_pred = self(x, training=True)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/base_layer.py", line 1036, in __call__
    outputs = call_context.current_call_stack.call(self, args, kwargs)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/base_layer.py", line 1006, in call
    return self.call(*args, **kwargs)
  File "model.py", line 31, in call
    x = self.flatten(x)
  File "/usr/local/lib/python3.9/dist-packages/keras/layers/reshaping/flatten.py", line 119, in call
    return array_ops.reshape(inputs, [batch_size, -1])
  File "{_OPS}/array_ops.py", line 65, in reshape
    return gen_array_ops.reshape(tensor, shape, name=name)
  File "{_OPS}/array_ops.py", line 661, in shape
    return shape_internal(input, name, optimize, out_type)
tensorflow.python.framework.errors_impl.InvalidArgumentError: Input to reshape is a tensor with 131072 values, but the requested shape requires a multiple of 65536
\t [[node sequential/flatten/Reshape (defined at model.py:31) ]]
\t [[{{node sequential/flatten/Reshape}}]]
"""

# ── Trace 2 ──────────────────────────────────────────────────────────────────
# A recently merged change removed gradient clipping before the loss step.
# After ~400 steps the weights drift enough that logits hit float32 overflow
# (+/-3.4e38). sigmoid_cross_entropy_with_logits computes softplus(logits)
# which overflows to inf, then log(inf) = inf, then inf - inf = NaN.
# The trace surfaces in abs() because TF validates tensor values there.
TF_TRACE_2 = f"""\
Traceback (most recent call last):
  File "train.py", line 94, in <module>
    history = model.fit(train_ds, epochs=50, callbacks=[checkpoint, tensorboard])
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 1184, in fit
    tmp_logs = self.train_function(iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 853, in train_function
    return step_function(self, iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 842, in step_function
    outputs = model.distribute_strategy.run(run_step, args=(data,))
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 831, in run_step
    outputs = model.train_step(data)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 795, in train_step
    loss = self.compiled_loss(y, y_pred, regularization_losses=self.losses)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/compile_utils.py", line 201, in __call__
    loss_value = loss_obj(y_t, y_p, sample_weight=sw)
  File "/usr/local/lib/python3.9/dist-packages/keras/losses.py", line 139, in __call__
    losses = call_fn(y_true, y_pred)
  File "/usr/local/lib/python3.9/dist-packages/keras/losses.py", line 243, in call
    return self.fn(y_true, y_pred, **self._fn_kwargs)
  File "/usr/local/lib/python3.9/dist-packages/keras/losses.py", line 1788, in binary_crossentropy
    return backend.binary_crossentropy(y_true, y_pred, from_logits=from_logits)
  File "/usr/local/lib/python3.9/dist-packages/keras/backend.py", line 5204, in binary_crossentropy
    return nn.sigmoid_cross_entropy_with_logits(labels=target, logits=output)
  File "{_OPS}/nn_impl.py", line 112, in sigmoid_cross_entropy_with_logits
    softplus = math_ops.softplus(logits)
  File "{_OPS}/math_ops.py", line 392, in abs
    return gen_math_ops._abs(x, name=name)
tensorflow.python.framework.errors_impl.InvalidArgumentError: 2 root error(s) found.
  (0) INVALID_ARGUMENT: Input tensor contains Inf/NaN values.
\t [[node sequential/output/Sigmoid (defined at train.py:94) ]]
  (1) INVALID_ARGUMENT: Input tensor contains Inf/NaN values.
\t [[node sequential/output/Sigmoid_1 (defined at train.py:94) ]]
0 successful operations.
0 derived errors ignored.
"""

# ── Trace 3 ──────────────────────────────────────────────────────────────────
# A custom training loop accumulates gradients over 8 micro-batches before
# applying them. A recently introduced bug skips the divide-by-accumulation-steps
# normalisation, so the effective gradient magnitude is 8x larger than intended.
# clip_by_global_norm receives a norm of Inf and cannot proceed.
TF_TRACE_3 = f"""\
Traceback (most recent call last):
  File "train.py", line 148, in train_epoch
    optimizer.apply_gradients(zip(grads, model.trainable_variables))
  File "/usr/local/lib/python3.9/dist-packages/keras/optimizers/optimizer_v2/optimizer_v2.py", line 635, in apply_gradients
    return self._distributed_apply(distribution, grads_and_vars, name, experimental_aggregate_gradients)
  File "/usr/local/lib/python3.9/dist-packages/keras/optimizers/optimizer_v2/optimizer_v2.py", line 702, in _distributed_apply
    reduced = distribution.extended.reduce_to(ds_reduce_util.ReduceOp.SUM, grad, destinations=var)
  File "/usr/local/lib/python3.9/dist-packages/keras/optimizers/optimizer_v2/optimizer_v2.py", line 765, in _aggregate_gradients
    grads_and_vars = self._deduplicate_indexed_slices(grads_and_vars)
  File "train.py", line 131, in train_step
    grads, global_norm_val = tf.clip_by_global_norm(tape.gradient(loss, model.trainable_variables), clip_norm=1.0)
  File "{_OPS}/clip_ops.py", line 300, in clip_by_global_norm
    use_norm = global_norm(t_list, name) if norm is None else norm
  File "{_OPS}/clip_ops.py", line 248, in global_norm
    global_norm = math_ops.sqrt(math_ops.reduce_sum(values))
  File "{_OPS}/math_ops.py", line 2229, in reduce_sum
    return gen_math_ops._sum(input_tensor, axis, keepdims=keepdims, name=name)
tensorflow.python.framework.errors_impl.InvalidArgumentError: Gradient clipping failed: global norm is Inf. Verify that the loss computation and gradient aggregation are numerically stable.
\t [[node clip_by_global_norm/global_norm/add_n (defined at train.py:131) ]]
"""

# ── Trace 4 ──────────────────────────────────────────────────────────────────
# A preprocessing change silently added a keepdims=True to a label reduction,
# making label tensors shape (batch, 1) instead of (batch,).
# TF's data validation asserts expected rank at the start of each epoch.
# The assertion fires deep in check_ops and the error message gives only
# actual vs expected values — not which preprocessing step caused it.
TF_TRACE_4 = f"""\
Traceback (most recent call last):
  File "train.py", line 94, in <module>
    history = model.fit(train_ds, epochs=20, validation_data=val_ds)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 1184, in fit
    tmp_logs = self.train_function(iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 853, in train_function
    return step_function(self, iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 842, in step_function
    outputs = model.distribute_strategy.run(run_step, args=(data,))
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 831, in run_step
    outputs = model.train_step(data)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 791, in train_step
    y_pred = self(x, training=True)
  File "/usr/local/lib/python3.9/dist-packages/keras/utils/tf_utils.py", line 491, in wrapper
    return fn(*args, **kwargs)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/base_layer.py", line 1007, in call
    return self.call(*args, **kwargs)
  File "pipeline.py", line 77, in call
    tf.debugging.assert_rank(labels, expected_rank, message="label rank mismatch — check preprocessing")
  File "/usr/local/lib/python3.9/dist-packages/tensorflow/python/ops/check_ops.py", line 790, in assert_rank_v2
    return assert_rank(x, rank, message=message, name=name)
  File "{_OPS}/check_ops.py", line 436, in _binary_assert
    condition, data, summarize, name, op_func)
  File "{_OPS}/check_ops.py", line 83, in _assert_static
    raise errors.InvalidArgumentError(node_def=None, op=None, message=condition_static)
tensorflow.python.framework.errors_impl.InvalidArgumentError: label rank mismatch — check preprocessing [Op:Assert] name: assert_rank
Condition x == y did not hold.
  x (rank(labels)) = 2
  y (expected_rank) = 1
"""

# ── Trace 5 ──────────────────────────────────────────────────────────────────
# The vocabulary was truncated from 50k to 32k tokens to reduce model size,
# but the tokeniser config was not updated. Token IDs above 32000 appear in
# the first batch containing uncommon words, causing embedding_lookup to
# fail with an out-of-bounds index. The trace goes through the full Keras
# embedding layer call stack before reaching the ops layer.
TF_TRACE_5 = f"""\
Traceback (most recent call last):
  File "train.py", line 94, in <module>
    history = model.fit(train_ds, epochs=10, callbacks=[lr_scheduler, checkpoint])
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 1184, in fit
    tmp_logs = self.train_function(iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 853, in train_function
    return step_function(self, iterator)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 842, in step_function
    outputs = model.distribute_strategy.run(run_step, args=(data,))
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 831, in run_step
    outputs = model.train_step(data)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/training.py", line 791, in train_step
    y_pred = self(x, training=True)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/base_layer.py", line 1036, in __call__
    outputs = call_context.current_call_stack.call(self, args, kwargs)
  File "/usr/local/lib/python3.9/dist-packages/keras/engine/base_layer.py", line 1006, in call
    return self.call(*args, **kwargs)
  File "model.py", line 19, in call
    x = self.embedding(token_ids)
  File "/usr/local/lib/python3.9/dist-packages/keras/layers/core/embedding.py", line 197, in call
    out = embedding_ops.embedding_lookup_v2(self.embeddings, inputs)
  File "{_OPS}/embedding_ops.py", line 269, in embedding_lookup
    return embedding_lookup_v2(params, ids, max_norm=max_norm, name=name)
  File "{_OPS}/embedding_ops.py", line 377, in embedding_lookup_v2
    return _embedding_lookup_and_transform(params=params, ids=ids, max_norm=max_norm, name=name)
  File "{_OPS}/embedding_ops.py", line 93, in _embedding_lookup_and_transform
    result = _clip(result, ids, max_norm)
tensorflow.python.framework.errors_impl.InvalidArgumentError: 2 root error(s) found.
  (0) INVALID_ARGUMENT: indices[4] = 34521 is not in [0, 32000)
\t [[node model/embedding/embedding_lookup/Identity (defined at model.py:19) ]]
  (1) INVALID_ARGUMENT: indices[4] = 34521 is not in [0, 32000)
\t [[node model/embedding/embedding_lookup/Identity_1 (defined at model.py:19) ]]
0 successful operations.
0 derived errors ignored.
"""

# ── Preset registry (used by the web app) ────────────────────────────────────
TF_PRESETS = {
    "tf_trace_1": {
        "label": "InvalidArgumentError — reshape shape mismatch (flatten layer)",
        "trace": TF_TRACE_1,
    },
    "tf_trace_2": {
        "label": "InvalidArgumentError — NaN in sigmoid_cross_entropy (logit overflow)",
        "trace": TF_TRACE_2,
    },
    "tf_trace_3": {
        "label": "InvalidArgumentError — Inf gradient norm in clip_by_global_norm",
        "trace": TF_TRACE_3,
    },
    "tf_trace_4": {
        "label": "InvalidArgumentError — label rank mismatch in assert_rank",
        "trace": TF_TRACE_4,
    },
    "tf_trace_5": {
        "label": "InvalidArgumentError — OOB embedding index after vocab truncation",
        "trace": TF_TRACE_5,
    },
}
