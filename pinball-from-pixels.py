""" Majority of this code was copied directly from Andrej Karpathy's gist:
https://gist.github.com/karpathy/a4166c7fe253700972fcbc77e4ea32c5 """

""" Trains an agent with (stochastic) Policy Gradients on Pinball. Uses OpenAI Gym. """
import numpy as np
import _pickle as pickle
import gym
import time
import sys
import random

from gym import wrappers

# hyperparameters to tune
H = 200 # number of hidden layer neurons
A = 6 # number of actions
batch_size = 10 # used to perform a RMS prop param update every batch_size steps
learning_rate = 1e-3 # learning rate used in RMS prop
gamma = 0.99 # discount factor for reward
decay_rate = 0.99 # decay factor for RMSProp leaky sum of grad^2

# Config flags - video output and res
resume = False # resume training from previous checkpoint (from save.p  file)?
render = True # render video output?

# model initialization
D = 188*160 # input dimensionality: 188x160 grid
if resume:
  model = pickle.load(open('save-pinball.p', 'rb'))
else:
  model = {}
  model['W1'] = np.random.randn(H,D) / np.sqrt(D) # "Xavier" initialization - Shape will be H x D
  model['W2'] = np.random.randn(A, H) / np.sqrt(H) # Shape will be H

grad_buffer = { k : np.zeros_like(v) for k,v in model.items() } # update buffers that add up gradients over a batch
rmsprop_cache = { k : np.zeros_like(v) for k,v in model.items() } # rmsprop memory

def sigmoid(x):
  return 1.0 / (1.0 + np.exp(-x)) # sigmoid "squashing" function to interval [0,1]

def prepro(I):
  """ prepro 250x160x3 uint8 frame into 30,080 (188x160) 1D float vector """
  I = I[29:217] # crop - remove 29px from start & 33px from end of image in x, to reduce redundant parts of image (i.e. after ball passes paddle)
  #I = I[::2,::2,0] # downsample by factor of 2.
  I = I[:, :, 0] #only need red value to differentiate between colors
  #np.set_printoptions(threshold=sys.maxsize)
  return I.astype(float).ravel() # ravel flattens an array and collapses it into a column vector

def discount_rewards(r):
  """ take 1D float array of rewards and compute discounted reward """
  """ this function discounts from the action closest to the end of the completed game backwards
  so that the most recent action has a greater weight """
  discounted_r = np.zeros_like(r)
  running_add = 0
  for t in reversed(range(0, r.size)): # xrange is no longer supported in Python 3, replace with range
    if r[t] != 0: running_add = 0 # reset the sum, since this was a game boundary (pong specific!)
    running_add = running_add * gamma + r[t]
    discounted_r[t] = running_add
  return discounted_r

def policy_forward(x):
  """This is a manual implementation of a forward prop"""
  h = np.dot(model['W1'], x) # (H x D) . (D x 1) = (H x 1) (200 x 1)
  h[h<0] = 0 # ReLU introduces non-linearity
  p = []
  for i in range(0, A):
    p.append(sigmoid(np.dot(model['W2'][i], h))) # This is a logits function and outputs a decimal.   (1 x H) . (H x 1) = 1 (scalar)
  return p, h # return probability of taking action 2 (UP), and hidden state

def policy_backward(eph, epx, epdlogp):
  """ backward pass. (eph is array of intermediate hidden states) """
  """ Manual implementation of a backward prop"""
  """ It takes an array of the hidden states that corresponds to all the images that were
  fed to the NN (for the entire episode, so a bunch of games) and their corresponding logp"""
  dW2, dh= [],np.empty([A,eph.shape[0], eph.shape[1]])
  #time.sleep(100)
  for i in range(0,A):
    dW2.append(np.dot(eph.T, epdlogp[:, i]).ravel())
    #dh.append(np.outer(epdlogp[:,i], model['W2']))
    #print("dh[i]: ")
    #print(dh[i].shape) #num actions x H
    #print("eplogd[:,i]: ")
    #print(epdlogp.shape) # num actions x A
    dh[i] = np.outer(epdlogp[:,i], model['W2'][i])
  #print("we here again xx2") 
  np.set_printoptions(threshold=10000)
  for i in range(0,A):
    dh[i, eph <= 0] = 0 # backpro prelu
  #print("we here")
  #print(dh.T.shape)
  #print(epx.shape)
  temp = []
  for i in range(0,A):
    temp.append(np.dot(dh[i].T, epx))
  dW1 = temp[0]
  for i in range(1,A):
    np.add(dW1, temp[i])
  np.divide(dW1, A)
  return {'W1':dW1, 'W2':dW2}

env = gym.make("VideoPinball-v0")
#env = wrappers.Monitor(env, 'tmp/pong-base', force=True) # record the game as as an mp4 file
observation = env.reset()
prev_x = None # used in computing the difference frame
xs,hs,dlogps,drs = [],[],[],[]
running_reward = None
reward_sum = 0
episode_number = 0

while True:
  if render: env.render()

  # preprocess the observation, set input to network to be difference image
  cur_x = prepro(observation)
  # we take the difference in the pixel input, since this is more likely to account for interesting information
  # e.g. motion
  x = cur_x - prev_x if prev_x is not None else np.zeros(D)
  prev_x = cur_x

  # forward the policy network and sample an action from the returned probability
  aprob, h = policy_forward(x)
  # The following step is randomly choosing a number which is the basis of making an action decision
  # If the random number is less than the probability of UP output from our neural network given the image
  # then go down.  The randomness introduces 'exploration' of the Agent
  #action = 2 if np.random.uniform() < aprob else 3 # roll the dice! 2 is UP, 3 is DOWN, 0 is stay the same
  #2 is both paddles up, 3 is right paddle up, 4 is left paddle up, 5 is pull bumper back, 6 fire bumper, except maybe 1 is?
  #action = random.choices(range(0,8), weights = aprob)
  action = random.choices(range(0,A), aprob)[0]
  
  # record various intermediates (needed later for backprop).
  # This code would have otherwise been handled by a NN library
  xs.append(x) # observation
  hs.append(h) # hidden state
  y = []
  for i in range(0,A):
    y.append(1 if action == i else 0) # a "fake label" - this is the label that we're passing to the neural network
  # to fake labels for supervised learning. It's fake because it is generated algorithmically, and not based
  # on a ground truth, as is typically the case for Supervised learning

  dlogps.append(y - aprob[action]) # grad that encourages the action that was taken to be taken (see http://cs231n.github.io/neural-networks-2/#losses if confused)
  
  # step the environment and get new measurements
  observation, reward, done, info = env.step(action)
  reward_sum += reward
  drs.append(reward) # record reward (has to be done after we call step() to get reward for previous action)

  if done: # an episode finished
    episode_number += 1

    # stack together all inputs, hidden states, action gradients, and rewards for this episode
    epx = np.vstack(xs)
    eph = np.vstack(hs)
    epdlogp = np.vstack(dlogps)
    epr = np.vstack(drs)
    xs,hs,dlogps,drs = [],[],[],[] # reset array memory

    # compute the discounted reward backwards through time
    discounted_epr = discount_rewards(epr)
    # standardize the rewards to be unit normal (helps control the gradient estimator variance)
    discounted_epr -= np.mean(discounted_epr)
    discounted_epr /= np.std(discounted_epr)

    epdlogp *= discounted_epr # modulate the gradient with advantage (Policy Grad magic happens right here.)
    grad = policy_backward(eph, epx, epdlogp)
    for k in model: grad_buffer[k] += grad[k] # accumulate grad over batch

    # perform rmsprop parameter update every batch_size episodes
    if episode_number % batch_size == 0:
      for k,v in model.items():     
        g = grad_buffer[k] # gradient
        rmsprop_cache[k] = decay_rate * rmsprop_cache[k] + (1 - decay_rate) * g**2
        model[k] += learning_rate * g / (np.sqrt(rmsprop_cache[k]) + 1e-5)
        grad_buffer[k] = np.zeros_like(v) # reset batch gradient buffer

    # boring book-keeping
    running_reward = reward_sum if running_reward is None else running_reward * 0.99 + reward_sum * 0.01
    print ('resetting env. episode #' + str(episode_number) + ' reward total was %f. running mean: %f' % (reward_sum, running_reward))
    if episode_number % 100 == 0: pickle.dump(model, open('save-pinball.p', 'wb'))
    reward_sum = 0
    observation = env.reset() # reset env
    prev_x = None

if reward != 0: # Pong has either +1 or -1 reward exactly when game ends.
    print ('ep %d: game finished, reward: %f' % (episode_number, reward)) + ('' if reward == -1 else ' !!!!!!!!')