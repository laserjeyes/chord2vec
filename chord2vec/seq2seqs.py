"""Library for creating sequence-to-sequences models in TensorFlow. 
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# We disable pylint because we need python3 compatibility.
from six.moves import xrange  # pylint: disable=redefined-builtin
from six.moves import zip     # pylint: disable=redefined-builtin

import tensorflow as tf 
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import embedding_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import nn_ops
from tensorflow.python.ops import rnn
from tensorflow.python.ops import rnn_cell
from tensorflow.python.ops import variable_scope



def embedding_rnn_decoders(num_decoders,all_decoder_inputs, initial_state, cell, num_symbols,
	embedding_size, output_projection=None,
	feed_previous=False,
	update_embedding_for_previous=True, scope=None):
	"""RNN decoder with embedding and a pure-decoding option.

	Args:
	num_decoders: Integer; number of sequences to output 
	all_decoder_inputs: A list num_decoders lists of 1D batch-sized int32 Tensors (decoder inputs).
	initial_state: 2D Tensor [batch_size x cell.state_size].
	cell: rnn_cell.RNNCell defining the cell function.
	num_symbols: Integer, how many symbols come into the embedding.
	embedding_size: Integer, the length of the embedding vector for each symbol.
	output_projection: None or a pair (W, B) of output projection weights and
	biases; W has shape [output_size x num_symbols] and B has
	shape [num_symbols]; if provided and feed_previous=True, each fed
	previous output will first be multiplied by W and added B.
	feed_previous: Boolean; if True, only the first of decoder_inputs will be
	used (the "GO" symbol), and all other decoder inputs will be generated by:
	next = embedding_lookup(embedding, argmax(previous_output)),
	In effect, this implements a greedy decoder. It can also be used
	during training to emulate http://arxiv.org/abs/1506.03099.
	If False, decoder_inputs are used as given (the standard decoder case).
	update_embedding_for_previous: Boolean; if False and feed_previous=True,
	only the embedding for the first symbol of decoder_inputs (the "GO"
		symbol) will be updated by back propagation. Embeddings for the symbols
	generated from the decoder itself remain unchanged. This parameter has
	no effect if feed_previous=False.
	scope: VariableScope for the created subgraph; defaults to
	"embedding_rnn_decoder".

	Returns:
	A tuple of the form (outputs, state), where:
	outputs: A list of the same length as decoder_inputs of 2D Tensors with
	shape [batch_size x output_size] containing the generated outputs.
	state: The state of each decoder cell in each time-step. This is a list
	with length len(decoder_inputs) -- one item for each time-step.
	It is a 2D Tensor of shape [batch_size x cell.state_size].

	Raises:
	ValueError: When output_projection has the wrong shape.
	"""
	if output_projection is not None:
		proj_weights = ops.convert_to_tensor(output_projection[0],
			dtype=dtypes.float32)
		proj_weights.get_shape().assert_is_compatible_with([None, num_symbols])
		proj_biases = ops.convert_to_tensor(
			output_projection[1], dtype=dtypes.float32)
		proj_biases.get_shape().assert_is_compatible_with([num_symbols])

	with variable_scope.variable_scope(scope or "embedding_rnn_decoder"):
		embedding = variable_scope.get_variable("embedding",
			[num_symbols, embedding_size])
		loop_function = _extract_argmax_and_embed(embedding, output_projection,
			update_embedding_for_previous) if feed_previous else None
		all_outputs = []
		all_states = []
		d = 0
		for decoder_inputs in all_decoder_inputs:
			emb_inp = (embedding_ops.embedding_lookup(embedding, i) for i in decoder_inputs)
			outputs, states = tf.nn.seq2seq.rnn_decoder(emb_inp, initial_state, cell,
				loop_function=loop_function,scope="rnn_decoder{0}".format(d))
			all_outputs.append(outputs)
			all_states.append(states)
			d += 1
		return all_outputs, all_states

def embedding_rnn_seq2seqs(encoder_inputs,num_decoders,  all_decoder_inputs, cell,
	num_encoder_symbols, num_decoder_symbols,
	embedding_size, output_projection=None,
	feed_previous=False, dtype=dtypes.float32,
	scope=None):
	"""Embedding RNN sequence-to-sequences model.

	This model first embeds encoder_inputs by a newly created embedding (of shape
		[num_encoder_symbols x input_size]). Then it runs an RNN to encode
	embedded encoder_inputs into a state vector. Next, it embeds decoder_inputs
	by another newly created embedding (of shape [num_decoder_symbols x
		input_size]). Then it runs RNN decoder, initialized with the last
	encoder state, on embedded decoder_inputs.

	Args: 
	encoder_inputs: A list of 1D int32 Tensors of shape [batch_size].
	num_decoders: Integer; number of sequences to output 
	decoder_inputs: A list num_decoder lists of 1D int32 Tensors of shape [batch_size].
	cell: rnn_cell.RNNCell defining the cell function and size.
	num_encoder_symbols: Integer; number of symbols on the encoder side.
	num_decoder_symbols: Integer; number of symbols on the decoder side.
	embedding_size: Integer, the length of the embedding vector for each symbol.
	output_projection: None or a pair (W, B) of output projection weights and
	biases; W has shape [output_size x num_decoder_symbols] and B has
	shape [num_decoder_symbols]; if provided and feed_previous=True, each
	fed previous output will first be multiplied by W and added B.
	feed_previous: Boolean or scalar Boolean Tensor; if True, only the first
	of decoder_inputs will be used (the "GO" symbol), and all other decoder
	inputs will be taken from previous outputs (as in embedding_rnn_decoder).
	If False, decoder_inputs are used as given (the standard decoder case).
	dtype: The dtype of the initial state for both the encoder and encoder
	rnn cells (default: tf.float32).
	scope: VariableScope for the created subgraph; defaults to
	"embedding_rnn_seq2seq" 

	Returns:
	Tuples of the form (outputs, state), where:
	outputs: A list of the same length as decoder_inputs of 2D Tensors with
	shape [batch_size x num_decoder_symbols] containing the generated
	outputs.
	state: The state of each decoder cell in each time-step. This is a list
	with length len(decoder_inputs) -- one item for each time-step.
	It is a 2D Tensor of shape [batch_size x cell.state_size].
	"""
	with variable_scope.variable_scope(scope or "embedding_rnn_seq2seq"):
	    # Encoder.
	    encoder_cell = rnn_cell.EmbeddingWrapper(
	    	cell, embedding_classes=num_encoder_symbols,
	    	embedding_size=embedding_size)
	    _, encoder_state = rnn.rnn(encoder_cell, encoder_inputs, dtype=dtype)

	    # Decoder.
	    if output_projection is None:
	    	cell = rnn_cell.OutputProjectionWrapper(cell, num_decoder_symbols)

	    	if isinstance(feed_previous, bool):

	    		return embedding_rnn_decoders(num_decoders,
	    			all_decoder_inputs, encoder_state, cell, num_decoder_symbols,
	    			embedding_size, output_projection=output_projection,
	    			feed_previous=feed_previous)

	    # If feed_previous is a Tensor, we construct 2 graphs and use cond.
	    def decoders(feed_previous_bool):
	    		reuse = None if feed_previous_bool else True
	    		with variable_scope.variable_scope(variable_scope.get_variable_scope(), reuse=reuse):
	    			all_outputs, all_states = embedding_rnn_decoders(num_decoders,
	    			all_decoder_inputs, encoder_state, cell, num_decoder_symbols,
	    			embedding_size, output_projection=output_projection,
	    			feed_previous=feed_previous_bool,
	    			update_embedding_for_previous=False)
	    			return all_outputs + [all_states]

	    all_outputs_and_states = control_flow_ops.cond(feed_previous,lambda: decoders(True), lambda: decoders(False))
	    return all_outputs_and_states[:-1], all_outputs_and_states[-1]

def sequences_loss(logits, targets, weights, num_decoders,
	average_across_timesteps=True, average_across_batch=True,
	softmax_loss_function=None, name=None):
	"""Product of weighted cross-entropy loss for sequences of logits, batch-collapsed.

	Args:
	logits: Lists of 2D Tensors of shape [batch_size x num_decoder_symbols] of size num_decoders.
	targets: Lists of 1D batch-sized int32 Tensors of the same lengths as logits.
	weights: List of 1D batch-sized float-Tensors of the same length as logits.
	average_across_timesteps: If set, divide the returned cost by the total
	label weight.
	average_across_batch: If set, divide the returned cost by the batch size.
	softmax_loss_function: Function (inputs-batch, labels-batch) -> loss-batch
	to be used instead of the standard softmax (the default if this is None).
	name: Optional name for this operation, defaults to "sequence_loss".

	Returns:
	A scalar float Tensor: The products of average log-perplexities per symbol (weighted).

	Raises:
	ValueError: If len(logits) is different from len(targets) or len(weights).
	"""
	if len(targets) != len(logits) or num_decoders != len(logits):
		raise ValueError("Lengths of logits and targets must be %d, not "
			"%d, %d." % (num_decoders, len(logits), len(targets)))
	losses = []    
	for i in xrange(num_decoders):
		losses.append(tf.nn.seq2seq.sequence_loss(logits[i],targets[i], weights[i],
			average_across_timesteps,average_across_batch,softmax_loss_function,name) ) 
	return math_ops.reduce_prod(losses)

def model_with_buckets(encoder_inputs, num_decoders, all_decoders_inputs, all_targets, weights,
		buckets, seq2seq, softmax_loss_function=None,
		per_example_loss=False, name=None):
	"""Create a sequence-to-sequence model with support for bucketing.

	The seq2seq argument is a function that defines a sequence-to-sequence model,
	e.g., seq2seq = lambda x, y: basic_rnn_seq2seq(x, y, rnn_cell.GRUCell(24))

	Args:
	encoder_inputs: A list of Tensors to feed the encoder; first seq2seq input.
	decoder_inputs: A list of Tensors to feed the decoder; second seq2seq input.
	targets: A list of 1D batch-sized int32 Tensors (desired output sequence).
	weights: List of 1D batch-sized float-Tensors to weight the targets.
	buckets: A list of pairs of (input size, output size) for each bucket.
	seq2seq: A sequence-to-sequence model function; it takes 2 input that
	agree with encoder_inputs and decoder_inputs, and returns a pair
	consisting of outputs and states (as, e.g., basic_rnn_seq2seq).
	softmax_loss_function: Function (inputs-batch, labels-batch) -> loss-batch
	to be used instead of the standard softmax (the default if this is None).
	per_example_loss: Boolean. If set, the returned loss will be a batch-sized
	tensor of losses for each sequence in the batch. If unset, it will be
	a scalar with the averaged loss from all examples.
	name: Optional name for this operation, defaults to "model_with_buckets".

	Returns:
	A tuple of the form (outputs, losses), where:
	outputs: The outputs for each bucket. Its j'th element consists of a list
	of 2D Tensors of shape [batch_size x num_decoder_symbols] (jth outputs).
	losses: List of scalar Tensors, representing losses for each bucket, or,
	if per_example_loss is set, a list of 1D batch-sized float Tensors.

	Raises:
	ValueError: If length of encoder_inputsut, targets, or weights is smaller
	than the largest (last) bucket.
	"""
	if len(encoder_inputs) < buckets[-1][0]:
		raise ValueError("Length of encoder_inputs (%d) must be at least that of la"
			"st bucket (%d)." % (len(encoder_inputs), buckets[-1][0]))
	#TODO: must check all target and weiths, not just first elem
	if len(all_targets[0]) < buckets[-1][1]:
	 	raise ValueError("Length of targets (%d) must be at least that of last"
	 		"bucket (%d)." % (len(targets), buckets[-1][1]))
	if len(weights[0]) < buckets[-1][1]:
		raise ValueError("Length of weights (%d) must be at least that of last"
					"bucket (%d)." % (len(weights), buckets[-1][1]))

	def bucket_decoders_inputs(b, decoders_list):
		return map(list,zip(*map(list, zip(*decoders_list))[:b]))

	all_inputs = encoder_inputs + all_decoders_inputs + all_targets + weights
	losses = []
	outputs = []
	with ops.op_scope(all_inputs, name, "model_with_buckets"):
		for j, bucket in enumerate(buckets):
			with variable_scope.variable_scope(variable_scope.get_variable_scope(),
				reuse=True if j > 0 else None):
				decoders_inputs = bucket_decoders_inputs(bucket[1], all_decoders_inputs)
				bucket_outputs, _ = seq2seq(encoder_inputs[:bucket[0]],
										decoders_inputs)
				outputs.append(bucket_outputs)

				bucket_targets = bucket_decoders_inputs(bucket[1], all_targets)
				bucket_weights = bucket_decoders_inputs(bucket[1],weights)
				if per_example_loss:
					
					losses.append(sequence_loss_by_example(
						outputs[-1], bucket_targets, bucket_weights,num_decoders,
						softmax_loss_function=softmax_loss_function))
				else:
					losses.append(sequences_loss(
						outputs[-1], bucket_targets, bucket_weights,num_decoders,
						softmax_loss_function=softmax_loss_function))
	return outputs[0], losses