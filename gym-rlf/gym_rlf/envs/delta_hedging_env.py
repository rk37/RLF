import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
import math
import numpy as np

from gym import spaces
from gym_rlf.envs.rlf_env import RLFEnv, action_space_normalizer, MIN_PRICE, MAX_PRICE
from gym_rlf.envs.Parameters import TickSize, OptionSize, T, S0, sigma_dh, kappa_dh, PENALTY_WEIGHT, MAX_PENALTY
from scipy.stats import norm

def insertion_sort(states, actions):
  state, action = states[-1], actions[-1]
  
  j = len(states) - 2
  while j >= 0 and state < states[j]: 
    states[j+1] = states[j]
    actions[j+1] = actions[j]
    j -= 1

  states[j+1] = state
  actions[j+1] = action
  return j + 1

def func_property(s0, s1, s2, a0, a1, a2):
  # Assume the state action pairs are sorted by s0 <= s1 <= s2.
  if s1 == s0 or s2 == s0: return 0
  grad1 = (a1 - a0) / (s1 - s0)
  grad2 = (a2 - a0) / (s2 - s0)
  if grad1 >= grad2: # concave
    return 0
  else:
    return min(MAX_PENALTY, PENALTY_WEIGHT * (grad2 - grad1)**2)
    
def BSM_call_price_and_delta(K, tau, St, sigma):
  if tau <= 0: return 0, 0
  # assuming zero interest rate
  numerator = math.log(St / K) + (.5 * sigma**2) * tau
  denominator = sigma * math.sqrt(tau)
  d1 = numerator / denominator
  d2 = d1 - denominator
  price = St * norm.cdf(d1) - K * norm.cdf(d2)
  delta = norm.cdf(d1)
  return price, delta
    

class DeltaHedgingEnv(RLFEnv):
  def __init__(self):
    super(DeltaHedgingEnv, self).__init__(T, 'delta_hedging_plots/')

    self.action_space = spaces.Box(low=-1, high=1, shape=(1,))
    # Use a Box to represent the observation space with params:
    # (underlying position), (time to maturity), and (underlying price).
    self.observation_space = spaces.Box(
      low=np.array([-OptionSize, 0, MIN_PRICE]),
      high=np.array([OptionSize, T, MAX_PRICE]),
      shape=(3,))

  def _next_price(self):
    rn = np.random.normal(0, 1., 1)[0]
    x = -.5 * sigma_dh**2 * self._step_counts + sigma_dh * rn
    p = S0 * np.exp(x)
    p = min(p, MAX_PRICE)
    p = max(p, MIN_PRICE)
    return p

  def reset(self):
    super(DeltaHedgingEnv, self).reset()

    self._prices[0] = S0
    self._option_prices = np.zeros(self._L+1)
    self._option_prices[0] = S0
    return self._get_state()

  def _get_state(self):
    return np.array([self._positions[self._step_counts], T - self._step_counts, self._prices[self._step_counts]])
    
  def _learn_func_property(self, func):
    j = insertion_sort(self._states, self._actions)
    num_data = len(self._states)
    if num_data <= 2: return 0

    penalty = 0
    for i in range(1, j):
      penalty += func(self._states[0], self._states[i], self._states[j],
                      self._actions[0], self._actions[i], self._actions[j])
    for i in range(j+1, num_data):
      penalty += func(self._states[0], self._states[j], self._states[i],
                      self._actions[0], self._actions[j], self._actions[i])
    return penalty / (num_data - 2)

  def step(self, action):
    ac = round(action[0] * action_space_normalizer)

    old_pos = self._positions[self._step_counts]
    old_price = self._prices[self._step_counts]
    old_option_price = self._option_prices[self._step_counts]
    self._step_counts += 1
    done = self._step_counts == self._L
    new_pos = self._positions[self._step_counts] = max(min(old_pos + ac, OptionSize), -OptionSize)
    new_price = self._prices[self._step_counts] = self._next_price()
    new_option_price = self._option_prices[self._step_counts] = old_option_price if done else\
      BSM_call_price_and_delta(S0, T - self._step_counts, new_price, sigma_dh)[0]

    trade_size = abs(new_pos - old_pos)
    cost = TickSize * (trade_size + 1e-2 * trade_size**2)
    PnL = (new_price - old_price) * old_pos + (new_option_price - old_option_price) - cost
    self._costs[self._step_counts] = cost
    self._profits[self._step_counts] = PnL + cost
    self._rewards[self._step_counts] = PnL - .5 * kappa_dh * PnL**2
      
    # Incorporate function property.
    self._states.append(new_price)
    if abs(old_pos) > 0:
      self._actions.append(ac/old_pos)
    else:
      self._actions.append(ac)
    self._rewards[self._step_counts] -= self._learn_func_property(func_property)

    return self._get_state(), self._rewards[self._step_counts], done, {}
 
  def render(self, mode='human'):
    super(DeltaHedgingEnv, self).render()

    t = np.linspace(0, self._L, self._L+1)
    fig, axs = plt.subplots(3, 1, figsize=(16, 24), constrained_layout=True)
    axs[0].plot(t, self._prices, label='stock prices')
    axs[0].plot(t, self._option_prices, label='option prices')
    axs[1].plot(t, self._positions)
    axs[2].plot(t, np.cumsum(self._rewards))
    axs[0].set_ylabel('price')
    axs[1].set_ylabel('position')
    axs[2].set_ylabel('cumulative P/L')
    axs[0].legend()
    plt.title('Out-of-sample simulation of RL agent')
    plt.xlabel('steps')
    plt.savefig('{}/plot_{}.png'.format(self._folder_name, self._render_counts))
    plt.close()
    plt.plot(t, np.cumsum(self._costs), label='cumulative costs')
    plt.plot(t, np.cumsum(self._profits), label='cumulative profits')
    plt.legend()
    plt.savefig('{}/costs_and_profits_plot_{}.png'.format(self._folder_name, self._render_counts))
    plt.close()
