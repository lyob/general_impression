import numpy as np
#import statsmodels.api as sm
import time
import il_exp_params as exp_params
import pickle
import os
from copy import copy, deepcopy

#Generate simulated inputs (Static FA)
def simulate_data(n_latent, n_out, n_sample, mixing_matrix, transition_matrix, sigma_latent = 1, sigma_out = 0.01):
    """simulate_data: generates data points for the Helmholtz Machine to learn on
    n_latent: number of latent states
    n_out: number of observed dimensions
    n_sample: number of samples to draw
    mixing_matrix: n_out x n_latent matrix mapping latent variables to observed
    sigma_latent: latent noise (default 1)
    sigma_out: observation noise"""
    
    #draw samples from the latent var
    latent_noise = np.random.normal(scale = sigma_latent, size = (n_latent, n_sample))
    latent = np.zeros((n_latent, n_sample))
    for ii in range(0, n_sample):
        if ii > 0:
            latent[:,ii] = transition_matrix @ latent[:,ii-1] + latent_noise[:,ii]
        else:
            latent[ii] = latent_noise[ii]
    
    #generate observation noise
    obs_noise = np.random.normal(scale = sigma_out, size = (n_out, n_sample))
    
    #produce observations from the latent variables and the noise
    data = mixing_matrix @ latent #+ obs_noise
    return data, latent

def set_learn_alg(network, learning_rate, switch_period):
    if exp_params.algorithm == 'wake_sleep':
        #learn_alg = WakeSleep(network, learning_rate, switch_period)
        learn_alg = LayeredImpression(network, learning_rate, switch_period)
    elif exp_params.algorithm == 'backprop':
        learn_alg = Backpropagation(network, learning_rate)
    elif exp_params.algorithm == 'reinforce':
        #learn_alg = LayeredREINFORCE(network, learning_rate)
        learn_alg = LayeredAlternatingREINFORCE(network, learning_rate, switch_period, decay = 0.9)
        #learn_alg = REINFORCE(network, learning_rate)
    return learn_alg

class Function:
    """Defines a function and its derivative.
    
    Attributes:
        f (function): An element-wise differentiable function that acts on a
            1-d numpy array of arbitrary dimension. May include a second
            argument for a label, e.g. for softmax-cross-entropy.
        f_prime (function): The element-wise derivative of f with respect to
            the first argument, must also act on 1-d numpy arrays of arbitrary
            dimension.
    """
    
    def __init__(self, f, f_prime):
        """Inits an instance of Function by specifying f and f_prime."""
        
        self.f = f
        self.f_prime = f_prime
        
def tanh_(z):

    return np.tanh(z)

def tanh_derivative(z):
    
    return 1 - np.tanh(z)**2

tanh = Function(tanh_, tanh_derivative)

right_slope = 1
left_slope = 0
def relu_(h):

    return np.maximum(0, right_slope * h) - np.maximum(0, left_slope * (-h))

def relu_derivative(h):

    return (h > 0) * (right_slope - left_slope) + left_slope

relu = Function(relu_,
                relu_derivative)

def sigmoid_(z):

    return 1 / (1 + np.exp(-z))

def sigmoid_derivative(z):

    return sigmoid_(z) * (1 - sigmoid_(z))

sigmoid = Function(sigmoid_,
                   sigmoid_derivative)

def cosine_similarity(mat_1, mat_2):
    vec_1 = np.ndarray.flatten(mat_1)
    vec_2 = np.ndarray.flatten(mat_2)
    vec_1_norm = vec_1 / np.linalg.norm(vec_1)
    vec_2_norm = vec_2 / np.linalg.norm(vec_2)
    
    return np.dot(vec_1_norm, vec_2_norm)

def unnormalized_similarity(mat_1, mat_2):
    vec_1 = np.ndarray.flatten(mat_1)
    vec_2 = np.ndarray.flatten(mat_2)
    
    return np.dot(vec_1, vec_2)

#define a Layer class
class Layer():
    """Parent class for all layers"""
    def __init__(self, N, N_parent, N_child, nonlinearity, sigma_gen, sigma_rec):
        """ Requirements
        N: number of neurons in the current layer
        N_parent: number of neurons in the above layer
        N_child: number of input neurons
        nonlinearity: function for the nonlinearity"""
        
        self.N = N
        self.N_parent = N_parent
        self.N_child = N_child
        self.nl = nonlinearity
        self.sigma_gen = sigma_gen
        self.sigma_rec = sigma_rec
        self.set_phase('wake')
        self.rec_switch = 0
        self.parent = None
        self.child = None
        
    def link(self, parent = None, child = None):
        self.parent = parent
        self.child = child
        
    def set_phase(self, phase):
        """sets the phase (wake or sleep) for the network"""
        self.phase = phase
        if phase == 'wake':
            self.delta = 1
        elif phase == 'sleep':
            self.delta = 0.
        elif phase == 'deep_sleep':
            self.delta = 0.0
        return
    
    def toggle_phase(self):
        """toggles the phase that the network is in"""
        if self.phase == 'wake':
            self.set_phase('sleep')
        elif self.phase == 'sleep':
            self.set_phase('wake')
            self.rec_switch = 1 #indication that a switch to the recognition state has occurred
        return
    
    def continue_phase(self):
        """remain in the current phase. Remove markers indicating phase switches"""
        self.rec_switch = 0
        return
    
    def redraw_mixed_phase(self):
        """randomly assigns each neuron to 'sleep' or 'wake'"""
        self.phase = 'mixed'
        self.delta = np.random.binomial(1,0.5, size = (self.N,))
        
    def reset(self):
        """defines how the network resets its state at the beginning of a new trial"""
        
        return
    
    def forward(self,x_child, x_parent):
        """defines how the network processes an input"""
        
        return
    
    def grad_gen(self):
        """returns a list of updates for each generative parameter in the layer"""
        return []
    
    def grad_rec(self):
        """returns a list of updates for each recognition parameter in the layer"""
        return []
    
    def e_trace_reinforce(self):
        """returns a list of the updates for each recognition parameter in the layer (calculated according to REINFORCE)"""
        return []
    
    def e_trace_alternating_rec(self):
        """returns a list of the updates for each recognition paramter in the layer, for the alternating network (ie. 0 if delta = 0)"""
        return []
    
    def e_trace_alternating_gen(self):
        """returns the list of the udpates for each generative parameter in the layer, for the alternating network (ie. 0 if delta = 1)"""
        return []
    
#define an input Layer
class InputLayer(Layer):
    """defines an Input Layer for the Helmholtz Machine"""
    def __init__(self, N, N_parent, nonlinearity, sigma_gen, sigma_rec, W_out = None):
        super().__init__(N, N_parent, N, nonlinearity, sigma_gen, sigma_rec)
        #initialize W_out
        if not(W_out is None):
            self.W_out = W_out
        else:
            self.W_out = np.random.normal(loc = 0, scale = 1/self.N_parent, size = (self.N, self.N_parent))
        
        self.params_list_gen = [self.W_out]
        self.params_list_rec = []
    
    def forward_generative(self):
        #generate observation noise
        self.noise_gen = np.random.normal(scale = self.sigma_gen, size = (self.N,))
        #produce observations from the latent variables and the noise
        self.h_mean_gen = self.W_out @ self.parent.h_gen
        self.h_gen = self.h_mean_gen + self.noise_gen
        
    def forward_recognition(self, h_child):
        self.h_child = h_child
        self.noise_rec = np.random.normal(scale = self.sigma_rec, size = (self.N,))
        self.h_mean_rec = self.h_child
        self.h_rec = self.h_mean_rec + self.noise_rec #an input layer just copies its inputs
        
    def forward(self):
        self.h_prev = self.h
        self.h = self.delta * self.h_rec + (1-self.delta) * self.h_gen

        self.h_pred_gen = self.W_out @ self.parent.h_rec
        self.h_pred_rec = self.h_child
        #self.layer_loss = np.sum((self.h - self.h_pred)**2)/self.sigma_gen**2
        self.layer_loss = self.delta *(np.sum((self.h - self.h_pred_gen)**2)/self.sigma_gen**2 - np.sum((self.h - self.h_mean_rec)**2/self.sigma_rec**2)) + (1-self.delta)* (np.sum((self.h - self.h_pred_rec)**2)/self.sigma_rec**2 - np.sum((self.h - self.h_mean_gen)**2)/self.sigma_gen**2)
    def reset(self):
        self.noise_gen = np.zeros((self.N,))
        self.h_mean_gen = np.zeros((self.N,))
        self.h_gen = np.zeros((self.N,))
        self.h_child = np.zeros((self.N_child,))
        self.h_rec = np.zeros((self.N,))
        self.h = np.zeros((self.N,))
    
    def grad_gen(self):
        g_hat = self.parent.h_rec
        G = (self.h_child - self.W_out @ g_hat)
        W_out_update = np.outer(G, g_hat)
            
        self.generative_update_list = [W_out_update]
        return self.generative_update_list
    
    def grad_rec(self):
        return []
    
    def e_trace_reinforce(self):
        return []
    
    def e_trace_alternating_rec(self):
        """returns a list of the updates for each recognition parameter in the layer, for the alternating network (ie. 0 if delta = 0)"""
        return []
    
    def e_trace_alternating_gen(self):
        """returns the list of the udpates for each generative parameter in the layer, for the alternating network (ie. 0 if delta = 1)"""
        return []
    
#define a feedforward Layer
class FeedforwardLayer(Layer):
    """defines a feedforward layer for the Helmholtz Machine"""
    def __init__(self, N, N_parent, N_child, nonlinearity, sigma_gen, sigma_rec, W_out = None, W_in = None, bias = False, top_layer = False):
        super().__init__(N, N_parent, N_child, nonlinearity, sigma_gen, sigma_rec)
        self.top_layer = top_layer
        if self.top_layer:
            self.W_out = None #if the feedforward layer is at the top of the hierarchy, do not give it a top-down projection
            self.transition_mat = 0.6 * np.eye(N)
            self.params_list_gen = [self.transition_mat]
        else:
            if not(W_out is None):
                self.W_out = W_out
            else:
                self.W_out = np.random.normal(loc = 0, scale = 1/self.N_parent, size = (self.N, self.N_parent))
            self.params_list_gen = [self.W_out]
        if not(W_in is None):
            self.W_in = W_in
        else:
            self.W_in = np.random.normal(loc = 0, scale = 1/self.N_child, size = (self.N, self.N_child))
        
        self.params_list_rec = [self.W_in]
        self.bias = np.zeros((self.N,))
        self.bias_gen = np.zeros((self.N,))
        if (bias):
            self.params_list_rec.append(self.bias)
            if not(top_layer):
                self.params_list_gen.append(self.bias_gen)
            self.biased = True
        else:
            self.biased = False
    
    def forward_generative(self):
        if not(self.parent is None):
            self.h_mean_gen = self.nl.f(self.W_out @ self.parent.h_gen + self.bias_gen)
        else:
            self.h_mean_gen = self.transition_mat @ self.h
        self.noise_gen = np.random.normal(scale = self.sigma_gen, size = (self.N,))
        self.h_gen = self.h_mean_gen + self.noise_gen
        
    def forward_recognition(self):
        self.h_pre_rec = self.W_in @ self.child.h_rec + self.bias
        self.h_mean_rec = self.nl.f(self.h_pre_rec)
        self.noise_rec = np.random.normal(scale = self.sigma_rec, size = (self.N,))
        self.h_rec = self.h_mean_rec + self.noise_rec
        
    def forward(self):
        self.h_prev = self.h
        self.h = self.delta * self.h_rec + (1-self.delta) * self.h_gen
        if self.rec_switch == 1:
            self.h_pred_gen = self.h_prev
        else:
            if not(self.parent is None):
                self.h_pred_gen = self.nl.f(self.W_out @ self.parent.h_rec + self.bias_gen)
            else:
                self.h_pred_gen = self.transition_mat @ self.h_prev
            
        self.h_pred_rec = self.nl.f(self.W_in @ self.child.h_gen + self.bias)
            
        #self.layer_loss = np.sum((self.h - self.h_pred)**2)/self.sigma_gen**2
        self.layer_loss = self.delta *(np.sum((self.h - self.h_pred_gen)**2)/(self.sigma_gen**2) - np.sum((self.h - self.h_mean_rec))/(self.sigma_rec**2)) + (1-self.delta)* (np.sum((self.h - self.h_pred_rec)**2)/(self.sigma_rec**2) - np.sum((self.h - self.h_mean_gen)**2)/(self.sigma_gen**2))
        
    def reset(self):
        self.noise_gen = np.zeros((self.N,))
        self.h_mean_gen = np.zeros((self.N,))
        self.h_gen = np.zeros((self.N,))
        self.h_child = np.zeros((self.N_child,))
        self.h_rec = np.zeros((self.N,))
        self.h = np.zeros((self.N,))
        
    def grad_gen(self):
        #update the generative transition matrix
        if self.rec_switch == 1: #if a recurrent switch has just occurred, there are no updates to the generative parameters
            if self.biased:
                self.generative_update_list = [0,0]
            else:
                self.generative_update_list = [0]
        else:
            if (self.top_layer):
                E = (self.h - self.transition_mat @ self.h_prev)
                transition_mat_update = np.diag(E * self.h_prev)
                self.generative_update_list = [transition_mat_update]
            else: #or update W_out if it's an intermediate layer
                g_hat = self.parent.h_rec
                h_pre_pred = self.W_out @ g_hat + self.bias_gen
                h_pred = self.nl.f(h_pre_pred)
                G = self.nl.f_prime(h_pre_pred) * (self.h_rec - h_pred)
                W_out_update = np.outer(G, g_hat)
                self.generative_update_list = [W_out_update]
                if self.biased:
                    bias_update = G
                    self.generative_update_list.append(bias_update)
        return self.generative_update_list
    
    def grad_rec(self):
        a_hat = self.child.h
        h_pre_pred = self.W_in @ a_hat + self.bias
        h_pred = self.nl.f(h_pre_pred)
        D = self.nl.f_prime(h_pre_pred) * (self.h - h_pred)
        W_in_update = np.outer(D, a_hat)
        if self.biased:
            bias_update = D
            self.recognition_update_list = [W_in_update, bias_update]
        else:
            self.recognition_update_list = [W_in_update]
        
        return self.recognition_update_list
    
    def e_trace_reinforce(self):
        if not(self.bias is None):
            e_trace_W_in = np.outer(self.nl.f_prime(self.h_pre_rec) * (self.h - self.h_mean_rec), self.child.h)
            e_trace_bias = self.nl.f_prime(self.h_pre_rec) * (self.h - self.h_mean_rec)
            self.e_trace_update_list = [e_trace_W_in, e_trace_bias]
        else:
            self.e_trace_update_list = [np.outer(self.nl.f_prime(self.h_pre_rec) * (self.h - self.h_mean_rec), self.child.h)]
        return self.e_trace_update_list

#define a layered Helmholtz Machine
class LayeredHM():
    def __init__(self, N_vec, sigma_gen_vec, sigma_rec_vec):
        self.N_vec = N_vec
        self.n_latent = np.sum(N_vec) #total # of neurons
        self.sigma_gen_vec = sigma_gen_vec
        self.sigma_rec_vec = sigma_rec_vec
        
        #construct the individual layers
        self.l0 = InputLayer(N_vec[0], N_vec[1], nonlinearity, sigma_gen_vec[0], sigma_rec_vec[0])
        self.l1 = FeedforwardLayer(N_vec[1], None, N_vec[0], nonlinearity, sigma_gen_vec[1], sigma_rec_vec[1], top_layer = True)
        
        #link together the individual layers
        self.l0.link(parent = self.l1, child = None)
        self.l1.link(parent = None, child = self.l0)
        
        self.layer_list = (self.l0, self.l1)
        self.set_phase('wake')
        
    def set_phase(self,phase):
        for layer in self.layer_list:
            layer.set_phase(phase)
        self.phase = phase
    
    def toggle_phase(self):
        for layer in self.layer_list:
            layer.toggle_phase()
        if self.phase == 'wake':
            self.phase = 'sleep'
        elif self.phase == 'sleep':
            self.phase = 'wake'
            self.rec_switch = 1 #variable indicates if a phase switch has just occurred
    
    def continue_phase(self):
        for layer in self.layer_list:
            layer.continue_phase()
        self.rec_switch = 0
    def reset(self):
        for layer in self.layer_list:
            layer.reset()
            
    def forward(self, x):
        #pass forward through the network for approximate inference
        self.l0.forward_recognition(x)
        self.l1.forward_recognition()
        
        #pass backward through the network for stimulus generation
        self.l1.forward_generative()
        self.l0.forward_generative()
        
        #based on the network phase, choose to set activities according to inference or generation
        self.l0.forward()
        self.l1.forward()
        
        self.loss_total = np.sum([layer.layer_loss for layer in self.layer_list])
        
# class TwoLayeredHM():
#     def __init__(self, N_vec, sigma_gen_vec, sigma_rec_vec):
#         self.N_vec = N_vec
#         self.n_latent = np.sum(N_vec) #total # of neurons
#         self.sigma_gen_vec = sigma_gen_vec
#         self.sigma_rec_vec = sigma_rec_vec
#
#         #construct the individual layers
#         self.l0 = InputLayer(N_vec[0], N_vec[1], nonlinearity, sigma_gen_vec[0], sigma_rec_vec[0])
#         self.l1 = FeedforwardLayer(N_vec[1], N_vec[2], N_vec[0], nonlinearity, sigma_gen_vec[1], sigma_rec_vec[1], bias = True, top_layer = False)
#         self.l2 = FeedforwardLayer(N_vec[2], None, N_vec[1], nonlinearity, sigma_gen_vec[2], sigma_rec_vec[2], bias = False, top_layer = True)
#         #link together the individual layers
#         self.l0.link(parent = self.l1, child = None)
#         self.l1.link(parent = self.l2, child = self.l0)
#         self.l2.link(parent = None, child = self.l1)
#         self.layer_list = (self.l0, self.l1, self.l2)
#         self.set_phase('wake')
#
#     def set_phase(self,phase):
#         for layer in self.layer_list:
#             layer.set_phase(phase)
#         self.phase = phase
#
#     def toggle_phase(self):
#         for layer in self.layer_list:
#             layer.toggle_phase()
#         if self.phase == 'wake':
#             self.phase = 'sleep'
#         elif self.phase == 'sleep':
#             self.phase = 'wake'
#             self.rec_switch = 1 #variable indicates if a phase switch has just occurred
#
#     def continue_phase(self):
#         for layer in self.layer_list:
#             layer.continue_phase()
#         self.rec_switch = 0
#
#     def reset(self):
#         for layer in self.layer_list:
#             layer.reset()
#
#     def forward(self, x):
#         #pass forward through the network for approximate inference
#         self.l0.forward_recognition(x)
#         self.l1.forward_recognition()
#         self.l2.forward_recognition()
#         #pass backward through the network for stimulus generation
#         self.l2.forward_generative()
#         self.l1.forward_generative()
#         self.l0.forward_generative()
#
#         #based on the network phase, choose to set activities according to inference or generation
#         self.l0.forward()
#         self.l1.forward()
#         self.l2.forward()
#
#         self.loss_total = np.sum([layer.layer_loss for layer in self.layer_list])
#
class LayeredLearningAlgorithm():
    
    def __init__(self, network, learning_rate):
        self.nn = network
        self.update_list_rec = []
        self.update_list_gen = []
        self.learning_stats = {'mean_update': [], 'moment_2': []}
        self.mean = []
        self.variance = []
        self.snr = []
        self.N_prev = 0
        
        for ii in range(0, len(self.nn.layer_list)):
            self.update_list_rec.append([0]*len(self.nn.layer_list[ii].params_list_rec))
            self.update_list_gen.append([0]*len(self.nn.layer_list[ii].params_list_gen))
            self.learning_stats['mean_update'].append([0]*len(self.nn.layer_list[ii].params_list_rec))
            self.learning_stats['moment_2'].append([0]*len(self.nn.layer_list[ii].params_list_rec))
            self.mean.append([0]*len(self.nn.layer_list[ii].params_list_rec))
            self.variance.append([0]*len(self.nn.layer_list[ii].params_list_rec))
            self.snr.append([0]*len(self.nn.layer_list[ii].params_list_rec))
            
        self.learning_rate = learning_rate
        
    def update_learning_vars(self, record_stats = False):
        return
        
    def assign_vars(self):
        #loop through all layers
        for ii in range(0, len(self.nn.layer_list)):
            #loop through all recognition parameters for that layer
            for jj in range(0, len(self.nn.layer_list[ii].params_list_rec)):
                self.nn.layer_list[ii].params_list_rec[jj] += self.learning_rate * self.update_list_rec[ii][jj] / exp_params.recognition_scale
            #loop through all generative parameters for that layer
            for jj in range(0, len(self.nn.layer_list[ii].params_list_gen)):
                self.nn.layer_list[ii].params_list_gen[jj] += self.learning_rate * self.update_list_gen[ii][jj]
    
    def update_learning_stats(self):
        """Keep a running average of the 1st and 2nd moments of the updates to the input weights. This is useful for comparison across algorithms"""
        for ii in range(0, len(self.nn.layer_list)):
            for jj in range(0, len(self.update_list_rec[ii])):
                self.learning_stats['mean_update'][ii][jj]= (self.learning_stats['mean_update'][ii][jj] * self.N_prev +  self.update_list_rec[ii][jj]) / (self.N_prev + 1)
                self.learning_stats['moment_2'][ii][jj] = (self.learning_stats['moment_2'][ii][jj] * self.N_prev + self.update_list_rec[ii][jj]**2)/ (self.N_prev + 1)
        self.N_prev += 1
        return
    
    def get_learning_stats(self):
        """Returns the mean, variance, and SNR across different parameters in W_in"""
        for ii in range(0, len(self.nn.layer_list)):
            for jj in range(0, len(self.update_list_rec[ii])):
                self.variance[ii][jj] = self.learning_stats['moment_2'][ii][jj] - self.learning_stats['mean_update'][ii][jj]**2
                self.mean[ii][jj] = self.learning_stats['mean_update'][ii][jj]
                self.snr[ii][jj] = self.mean[ii][jj]**2/self.variance[ii][jj]
        return self.mean, self.variance, self.snr
    
    def reset_learning(self):
        return
                
class LayeredImpression(LayeredLearningAlgorithm):
    def __init__(self, network, learning_rate, switch_period):
        super().__init__(network, learning_rate)
        self.switch_period = switch_period
        self.switch_counter = 0
    def update_learning_vars(self, record_stats = False):
        #the statistics functions only care about W_in, so we only run in the sleep phase if stats are being recorded
            
        #update the feedforward recognition weights
        if self.nn.phase == 'sleep':# and not(self.switch_counter == 0):
            for ii in range(0, len(self.nn.layer_list)):
                self.update_list_rec[ii] = self.nn.layer_list[ii].grad_rec()
        else:
            for ii in range(0, len(self.nn.layer_list)):
                self.update_list_rec[ii] = [0]*len(self.nn.layer_list[ii].params_list_rec)
                
        #update the top-down generative weights
        if self.nn.phase == 'wake':# and not(self.switch_counter == 0):
            for ii in range(0, len(self.nn.layer_list)):
                self.update_list_gen[ii] = self.nn.layer_list[ii].grad_gen()
        else:
            for ii in range(0, len(self.nn.layer_list)):
                self.update_list_gen[ii] = [0]*len(self.nn.layer_list[ii].params_list_gen)
        
        #if not(record_stats):
        #determine whether to transition phase (wake or sleep)
        if self.switch_period > 0:
            self.switch_counter = self.switch_counter + 1;
            if self.switch_counter > self.switch_period:
                self.nn.toggle_phase()
                self.switch_counter = 0
            else:
                self.nn.continue_phase()
                    
                    
# class LayeredREINFORCE(LayeredLearningAlgorithm):
#     def __init__(self, network, learning_rate, decay = 0.9, loss_decay = 0.99):
#         super().__init__(network, learning_rate)
#         self.e_trace = 0
#         self.e_trace_update = 0
#         self.e_trace_rec_list = []
#         self.e_trace_rec_update_list = []
#         self.e_trace_rec_update_prev = []
#         for ii in range(0, len(self.nn.layer_list)):
#             self.e_trace_rec_list.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_rec_update_list.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_rec_update_prev.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#         self.loss_avg = 0
#         self.decay = decay
#         self.loss_decay = loss_decay
#
#     def update_learning_vars(self, record_stats = False):
#         #self.loss_avg = (self.loss_decay) * self.loss_avg + (1-self.loss_decay) * self.nn.loss_total
#         self.loss_avg = 0#self.loss_decay * self.loss_avg + (1-self.loss_decay)*self.nn.loss_total
#         for ii in range(0, len(self.nn.layer_list)):
#             self.e_trace_rec_update_prev[ii] = self.e_trace_rec_update_list[ii]
#             self.e_trace_rec_update_list[ii] = self.nn.layer_list[ii].e_trace_reinforce()
#             for jj in range(0, len(self.nn.layer_list[ii].params_list_rec)):
#                 self.e_trace_rec_list[ii][jj] = self.e_trace_rec_update_list[ii][jj] + self.e_trace_rec_update_prev[ii][jj]
#                 self.update_list_rec[ii][jj] = (self.nn.loss_total- self.loss_avg) * self.e_trace_rec_list[ii][jj]
#
#
#         #all of the algorithms have the same update for the generative weights
#         for ii in range(0, len(self.nn.layer_list)):
#                 self.update_list_gen[ii] = self.nn.layer_list[ii].grad_gen()
#
# class LayeredAlternatingREINFORCE(LayeredLearningAlgorithm):
#     """Algorithm for performing REINFORCE while the network is in an alternating mode, rather than when delta = 1"""
#     def __init__(self, network, learning_rate, switch_period, decay = 1, loss_decay = 0.99):
#         super().__init__(network, learning_rate)
#         self.e_trace = 0
#         self.e_trace_update = 0
#         self.e_trace_rec_list = []
#         self.e_trace_gen_list = []
#         self.e_trace_rec_update_list = []
#         self.e_trace_rec_update_prev = []
#         self.e_trace_gen_update_list = []
#         self.e_trace_gen_update_prev = []
#         for ii in range(0, len(self.nn.layer_list)):
#             self.e_trace_rec_list.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_gen_list.append([0]*len(self.nn.layer_list[ii].params_list_gen))
#             self.e_trace_rec_update_list.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_rec_update_prev.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_gen_update_list.append([0]*len(self.nn.layer_list[ii].params_list_gen))
#             self.e_trace_gen_update_prev.append([0]*len(self.nn.layer_list[ii].params_list_gen))
#         self.loss_avg = 0
#         self.decay = decay
#         self.loss_decay = loss_decay
#
#         self.switch_period = switch_period
#         self.switch_counter = 0
#
#     def reset_learning(self, loss_reset = False):
#         for ii in range(0, len(self.nn.layer_list)):
#             self.e_trace_rec_list.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_gen_list.append([0]*len(self.nn.layer_list[ii].params_list_gen))
#             self.e_trace_rec_update_list.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_rec_update_prev.append([0]*len(self.nn.layer_list[ii].params_list_rec))
#             self.e_trace_gen_update_list.append([0]*len(self.nn.layer_list[ii].params_list_gen))
#             self.e_trace_gen_update_prev.append([0]*len(self.nn.layer_list[ii].params_list_gen))
#
#         if loss_reset:
#             self.loss_avg = 0
#
#     def update_learning_vars(self, record_stats = False):
#         #self.loss_avg = (self.loss_decay) * self.loss_avg + (1-self.loss_decay) * self.nn.loss_total
#         self.loss_avg = self.loss_decay * self.loss_avg + (1-self.loss_decay)*self.nn.loss_total
#
#         #First, compute the updates given by impression learning
#         for ii in range(0, len(self.nn.layer_list)):
#             self.update_list_gen[ii] = [(self.nn.layer_list[ii].delta)*grad for grad in self.nn.layer_list[ii].grad_gen()] #this is supposed to be 0 if delta = 0
#             self.update_list_rec[ii] = [(1-self.nn.layer_list[ii].delta)*grad for grad in self.nn.layer_list[ii].grad_rec()] #this is supposed to be 0 if delta = 1
#
#         for ii in range(0, len(self.nn.layer_list)):
#             self.e_trace_rec_update_prev[ii] = self.e_trace_rec_update_list[ii]
#             self.e_trace_gen_update_prev[ii] = self.e_trace_gen_update_list[ii]
#
#             self.e_trace_rec_update_list[ii] = self.nn.layer_list[ii].grad_rec()
#             self.e_trace_gen_update_list[ii] = self.nn.layer_list[ii].grad_gen()
#
#             #step 2, add on the update given by REINFORCE
#             for jj in range(0, len(self.nn.layer_list[ii].params_list_rec)):
#                 self.e_trace_rec_list[ii][jj] = (self.nn.layer_list[ii].delta)* self.e_trace_rec_update_list[ii][jj] + (self.decay)*self.e_trace_rec_list[ii][jj]#self.e_trace_rec_update_prev[ii][jj]
#                 self.update_list_rec[ii][jj] += (self.nn.loss_total- self.loss_avg) * self.e_trace_rec_list[ii][jj]
#
#             for jj in range(0, len(self.nn.layer_list[ii].params_list_gen)):
#                 self.e_trace_gen_list[ii][jj] = (1 - self.nn.layer_list[ii].delta)*self.e_trace_gen_update_list[ii][jj] + (self.decay)*self.e_trace_gen_list[ii][jj]#self.e_trace_gen_update_prev[ii][jj]
#                 self.update_list_gen[ii][jj] += (self.nn.loss_total - self.loss_avg) * self.e_trace_gen_list[ii][jj]
#
#         if self.switch_period > 0:
#             self.switch_counter = self.switch_counter + 1;
#             if self.switch_counter > self.switch_period:
#                 self.nn.toggle_phase()
#                 self.switch_counter = 0
#             else:
#                 self.nn.continue_phase()
#
#Define simulation
class Simulation():
    def __init__(self, data, learn_alg, nn, train = True, compare_algs = [], epoch_num = 1, learning_stats = False, nn_record = False, phase_switch = False, starting_phase = 'wake'):
        self.data = data
        self.learn_alg = learn_alg
        self.compare_algs = compare_algs
        self.nn = nn
        self.train = train
        self.learning_stats = learning_stats
        self.nn_record = nn_record
        self.epoch_num = epoch_num
        if nn_record:
            self.nn_list = []
        self.starting_phase = starting_phase
        self.phase_switch = phase_switch
    def run(self):
        T = self.data.shape[1] #total time
        if isinstance(self.nn, TwoLayeredHM):
            latent = np.zeros((self.nn.l1.N + self.nn.l2.N, T))
        elif isinstance(self.nn, LayeredHM):# or isinstance(self.nn, TwoLayeredHM):
            latent = np.zeros((self.nn.l1.N, T))

        loss = np.zeros((1,T))
        report_period = int(T*self.epoch_num/10)
        if report_period == 0:
            1 + 1
        nn_record_period = int(T*self.epoch_num/20)
        report_percent = 0
        t0 = time.time()
        self.nn.set_phase(self.starting_phase)
        for ee in range(0, self.epoch_num): #loop through data as many times as dictated by the # of epochs.
            self.nn.reset() #remove stored previous states from the network
            #self.nn.set_phase(self.starting_phase) #set the network to its initial phase
            if not(self.learn_alg is None):
                self.learn_alg.reset_learning()
            for alg in self.compare_algs:
                alg.reset_learning()
            for tt in range(0,T):
                if self.learning_stats:
                    1+1
                if np.mod(int(tt + T*ee), report_period) == 0:
                    print('Progress: ' + str(report_percent) + ' % complete')
                    print('Total time: ' + str(time.time() - t0) + ' seconds')
                    report_percent += 10
                    
                if self.nn_record and np.mod(tt + T*ee, nn_record_period) == 0:
                    if self.nn_record:
                        self.nn_list.append(deepcopy(self.nn))
                # process one datum
                self.nn.forward(self.data[:,tt])
        
                # update the learning variables/parameters
                if self.train:
                    self.learn_alg.update_learning_vars()
                    self.learn_alg.assign_vars()
                elif self.learning_stats:
                    for alg in self.compare_algs:
                        alg.update_learning_vars(record_stats = True)
                        alg.update_learning_stats()
                elif self.phase_switch:
                    self.learn_alg.update_learning_vars()
                
                # keep record of neural activations and loss
                if isinstance(self.nn, LayeredHM) or isinstance(self.nn, TwoLayeredHM):
                    latent[:,tt] = np.hstack([layer.h for layer in self.nn.layer_list[1::]]) #store a concatenation of all neural activities in the network
                    
                loss[:,tt] = self.nn.loss_total
        
        self.latent = latent
        self.loss = loss
        
        return latent, loss

#%% Core simulation
if __name__ == '__main__':
    if not(exp_params.mode in ('SNR', 'standard', 'Vocal_Digits')):
        np.random.seed(120994)
    #Run simulation and perform comparisons
    array_num = exp_params.array_num
    #simulate the data
    n_latent = exp_params.n_latent
    n_out = exp_params.n_out
    n_in = exp_params.n_in
    n_neurons = exp_params.n_neurons
    n_sample = exp_params.n_sample
    n_test = exp_params.n_test
    dt = exp_params.dt
    sigma_latent_data = 0.5 * np.sqrt(dt)
    mixing_matrix = np.random.normal(loc = 0, scale = 1/n_latent, size = (n_in, n_latent)) #observation matrix
    transition_matrix = (1 - sigma_latent_data**2) * np.eye(n_latent)
    if exp_params.mode == 'Vocal_Digits':
        n_digits = exp_params.n_digits
        data_train, data_latent_train = Vocal_Digits(n_sample, n_digits, hpc = not(exp_params.local))
        data_test, data_latent_test = Vocal_Digits(n_sample, n_digits, hpc = not(exp_params.local), test = True)
    else:
        data_train, data_latent_train = simulate_data(n_latent, n_out, n_sample, mixing_matrix, transition_matrix, sigma_latent = sigma_latent_data, sigma_out = 0.01)
        data_test, data_latent_test = simulate_data(n_latent, n_out, n_test, mixing_matrix, transition_matrix, sigma_latent = sigma_latent_data, sigma_out = 0.01)
    
    
    #build the neural network

    nonlinearity = tanh
    W_out = np.random.normal(loc = 0, scale = 1/n_neurons, size = (n_in, n_neurons))
    W_in = np.random.normal(loc = 0, scale = 1/n_in, size = (n_neurons, n_in))
    transition_mat = 0.6 * np.eye(n_neurons)
    sigma_latent = exp_params.sigma_latent
    sigma_obs_gen = exp_params.sigma_obs_gen
    if exp_params.mode in ('MNIST', 'Vocal_Digits'):
        sigma_latent_gen = exp_params.sigma_latent_gen
    else:
        sigma_latent_gen = sigma_latent_data
    
    if exp_params.mode in ('standard', 'MNIST', 'time_constant', 'switch_period', 'dimensionality', 'lr_optim', 'SNR', 'sinusoid'):
        network = LayeredHM([n_in, n_neurons], [sigma_obs_gen, sigma_latent_gen], [exp_params.sigma_in, sigma_latent])
    # elif exp_params.mode == ('Vocal_Digits'):
    #     network = TwoLayeredHM([n_in, n_neurons, 40], [sigma_obs_gen, sigma_obs_gen, sigma_latent_gen], [exp_params.sigma_in, sigma_latent, sigma_latent])
    #build the learning algorithm
    learning_rate = exp_params.learning_rate
    switch_period = exp_params.switch_period
    learn_alg = set_learn_alg(network, learning_rate, switch_period)
    
    if exp_params.mode in ('standard', 'MNIST', 'time_constant', 'switch_period', 'dimensionality', 'lr_optim', 'Vocal_Digits', 'sinusoid'):
        #run the training simulation
        sim = Simulation(data_train, learn_alg, network, train = True, epoch_num = exp_params.epoch_num, learning_stats = False, nn_record = True, starting_phase = 'wake')
        latent_train, loss = sim.run()
        
        #run the test simulation
        loss_mean = np.zeros((len(sim.nn_list),))
        counter = 0
        for nn in sim.nn_list:
            learn_alg_test = set_learn_alg(nn, learning_rate, switch_period)
            if exp_params.mode in ('switch_period'):
                phase_switch = False
            else:
                phase_switch = True
            test_sim = Simulation(data_test, learn_alg_test, nn, train = False, phase_switch = phase_switch)
            latent_test, loss_test = test_sim.run()
            loss_mean[counter] = np.mean(loss_test)
            counter = counter + 1
        
        #run the generative simulation
        if (not(exp_params.mode == 'MNIST')):
            gen_sim = Simulation(data_test, learn_alg, network, train = False, starting_phase = 'deep_sleep')
            latent_gen, loss_gen = gen_sim.run()
        else:
            gen_sim = []
            for ii in range(0, exp_params.gen_sim_num):
                gen_sim_temp = Simulation(data_test[:,0:50], learn_alg, network, train = False, starting_phase = 'deep_sleep')
                _,_ = gen_sim_temp.run()
                gen_sim.append(deepcopy(gen_sim_temp))
        
        
        #get a short test sequence for comparing wake/sleep alternation to just wake
        np.random.seed(1111)
        wake_sequence = Simulation(data_test, learn_alg, network, train = False)
        _,_ = wake_sequence.run()
        
        np.random.seed(1111)
        wake_sleep_sequence = Simulation(data_test, learn_alg, network, train = False, phase_switch = True)
        _,_ = wake_sleep_sequence.run()
        
        
    # elif exp_params.mode == 'SNR':
    #     #run the training simulation
    #     sim = Simulation(data_train, learn_alg, network, train = True, learning_stats = False, nn_record = True)
    #     latent_train, loss = sim.run()
    #
    #     test_sim = Simulation(data_test, learn_alg, network, train = False)
    #     latent_test, loss_test = test_sim.run()
    #
    #     data_compare, data_latent_compare = simulate_data(n_latent, n_out, exp_params.n_compare, mixing_matrix, transition_matrix, sigma_latent = sigma_latent_data, sigma_out = 0.01)
    #     #run a test simulation for each network frozen at a point during training time
    #     #compare the weight updates given by different learning algorithms
    #     mean_ws = []
    #     var_ws = []
    #     snr_ws = []
    #     mean_reinforce = []
    #     var_reinforce = []
    #     snr_reinforce = []
    #     mean_backprop = []
    #     var_backprop = []
    #     snr_backprop = []
    #     loss_mean = np.zeros((len(sim.nn_list),))
    #     counter = 0
    #     for nn in sim.nn_list:
    #         #construct a list of the learning algorithms to compare
    #
    #         learn_alg_test = set_learn_alg(nn, learning_rate, switch_period)
    #         test_sim = Simulation(data_test, learn_alg_test, nn, train = False, phase_switch = True)
    #         latent_test, loss_test = test_sim.run()
    #         loss_mean[counter] = np.mean(loss_test)
    #
    #         learn_alg_ws = LayeredImpression(nn, learning_rate, switch_period)
    #         learn_alg_reinforce = LayeredAlternatingREINFORCE(nn, learning_rate, switch_period, decay = 1)
    #
    #         compare_algs_ws = [learn_alg_ws]
    #         comparison_sim = Simulation(data_compare, None, nn, epoch_num = exp_params.epoch_num_snr, train = False, compare_algs = compare_algs_ws, learning_stats = True)
    #         np.random.seed(120994)
    #         _,_ = comparison_sim.run()
    #         mean, var, snr = learn_alg_ws.get_learning_stats()
    #         mean_ws.append(mean)
    #         var_ws.append(var)
    #         snr_ws.append(snr)
    #
    #         compare_algs_reinforce = [learn_alg_reinforce]
    #         comparison_sim = Simulation(data_compare, None, nn, epoch_num = exp_params.epoch_num_snr, train = False, compare_algs = compare_algs_reinforce, learning_stats = True)
    #         np.random.seed(120994)
    #         _,_ = comparison_sim.run()
    #
    #         mean, var, snr = learn_alg_reinforce.get_learning_stats()
    #         mean_reinforce.append(mean)
    #         var_reinforce.append(var)
    #         snr_reinforce.append(snr)
    #
    #         counter = counter + 1
    #
#%% Save
    if exp_params.save:
    #lump all of the results into one dictionary
        if exp_params.mode in ('standard', 'MNIST', 'time_constant', 'switch_period', 'dimensionality', 'Vocal_Digits', 'sinusoid'):
            result = {'test_sim': test_sim,# 'sim': sim, 
                      'gen_sim': gen_sim,
                      'data_test': data_test,
                      'data_latent_test': data_latent_test,
                      'loss_mean': loss_mean,
                      'network': network,
                      'wake_sequence': wake_sequence,
                      'wake_sleep_sequence': wake_sleep_sequence}
            if exp_params.mode == 'standard':
                filename = '/impression_'
            # elif exp_params.mode == 'MNIST':
            #     filename = '/impression_mnist_'
            # elif exp_params.mode == 'time_constant':
            #     filename = '/impression_tc_'
            # elif exp_params.mode == 'switch_period':
            #     filename = '/impression_sp_'
            # elif exp_params.mode == 'dimensionality':
            #     filename = '/impression_d_'
            # elif exp_params.mode == 'Vocal_Digits':
            #     filename = '/vocal_digits_'
        # elif exp_params.mode == 'SNR':
        #     result = {'mean_ws': mean_ws, 'var_ws': var_ws, 'snr_ws': snr_ws,
        #               'mean_reinforce': mean_reinforce, 'var_reinforce': var_reinforce, 'snr_reinforce': snr_reinforce,
        #               'mean_backprop': mean_backprop, 'var_backprop': var_backprop, 'snr_backprop': snr_backprop,
        #               'loss_mean': loss_mean}
        #     filename = '/impression_snr_'
            
        # elif exp_params.mode == 'lr_optim':
        #     result = {'loss_mean': loss_mean}
        #     filename = '/impression_lr_'

        # save the whole dictionary
        if exp_params.local:
            save_path = os.getcwd() + 'impression_data' + str(array_num)
        else:
            save_path = os.getcwd() + filename + str(array_num)
        with open(save_path, 'wb') as f:
            pickle.dump(result, f)
    
    