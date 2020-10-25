import numpy as np
from tqdm import tqdm

import matplotlib.pyplot as plt

from utils import c, ct, as_column, as_row

# https://dl.acm.org/doi/pdf/10.1109/TASLP.2016.2634118
# http://www.maths.lu.se/fileadmin/maths/personal_staff/Andreas_Jakobsson/openPEARLS.pdf


def get_window_length(lambda_: float):
	"""Get penalty window length
	lambda_:	forgetting factor
	"""
	return int(np.log(0.01) / np.log(lambda_))


class Pearls:
	def __init__(
		self,
		signal: np.array,
		lambda_: float,
		xi: float,
		H: int,
		fs: float,
		K_msecs: float,
		p1: float,
		p2: float,
		ss: float,
		mgi: int,
	):
		"""
		signal:     input signal (1 channel)
		lambda:     forgetting factor
		xi:         smoothing factor
		H:          maximum number of harmonics
		fs:         sampling frequency
		K_msecs:    number of milliseconds to produce a pitch
		p1:         penalty factor 1
		p2:         penalty factor 2
		ss:         step size for gradient descent
		mgi:        max gradient iterations for gradient descent
		"""
		self.s = signal
		self.complex_dtype = "complex_"
		self.float_dtype = "float64"
		self.L = len(signal)

		self.lambda_ = lambda_
		self.xi = xi
		self.H = H
		self.fs = fs
		self.K = int(np.floor(K_msecs * 1e-3 * fs))
		self.p1 = p1
		self.p2 = p2
		self.ss = ss
		self.mgi = mgi
		self.w_len = get_window_length(self.lambda_)

	def initialize_variables(self, f_int: tuple, f_spacing: float):
		"""
		f_int:      (min, max) frequency search interval
		f_spacing:  initial spacing between frequencies
		"""
		# Initialize frequency matrix as [harmonic, pitch]
		ps = np.arange(f_int[0], f_int[1] + 0.001, f_spacing, dtype=self.float_dtype)
		self.P = len(ps)
		self.f_mat = as_column(np.arange(1, self.H + 1)) * ps
		self.f_active = [True] * self.P

		# Initialize time variables
		self.t = np.arange(self.L + self.K) / self.fs
		self.t_stop = self.K
		self.tvec = self.t[: self.t_stop]

		# Initialize pitch-time matrix/vector
		self._update_a(fs_updated=True)

		# Initialize covariance matrix/vector
		self.R = self.a @ ct(self.a)
		self.r = self.s[0] * np.conj(self.a)

		# Initialize RLS filter coefficients
		n_coef = self.P * self.H
		self.rls = np.zeros((n_coef, 1), dtype=self.complex_dtype)

		# Initialize weights
		self.w_hat = np.zeros((n_coef, 1), dtype=self.complex_dtype)

		# Initialize result history
		self.rls_hist = np.zeros((n_coef, self.L), dtype=self.complex_dtype)
		self.w_hat_hist = np.zeros((n_coef, self.L), dtype=self.complex_dtype)
		self.freq_hist = np.zeros((self.P, self.L), dtype=self.complex_dtype)

	def _increment_time_vars(self):
		"""Increment time variables"""
		self.t_stop += 1
		self.tvec = self.t[self.t_stop - self.K : self.t_stop]

	def _update_a(self, fs_updated: bool):
		"""Update a vector and A matrix
		f_updated:  If updates has been done to the frequency matrix
		"""
		if fs_updated:
			self.A = np.exp(self.tvec * 2 * np.pi * 1j * as_column(self.f_mat.ravel()))
			self.a = as_column(self.A[:, -1])
		else:
			tval = self.t[self.t_stop - 1]
			self.a = np.exp(as_column(2 * np.pi * 1j * self.f_mat.ravel()) * tval)
			self.A = np.roll(self.A, -1, axis=1)
			self.A[:, -1] = self.a.ravel()

	def _update_covariance(self, s_val: float):
		"""Update covariance r vector and R matrix
		s_val:      signal value
		"""
		self.R = self.lambda_ * self.R + self.a @ ct(self.a)
		self.r = self.lambda_ * self.r + s_val * c(self.a)

	def run_algorithm(self):
		"""Run PEARLS algorithm through signal"""

		# If frequency matrix has been updated
		fs_upd = False

		for idx in range(self.L):
			if idx % 100 == 0:
				print(f"Sample {idx}/{self.L}")
			sval = self.s[idx]

			self._increment_time_vars()
			self._update_a(fs_upd)
			self._update_covariance(sval)
			# update penalty parameters
			self._gradient_descent()

	def _gradient_descent(self):
		"""Perform gradient descent on parameter weights"""
		for _ in range(self.mgi):
			v = self.w_hat + self.ss * (self.r - self.R @ self.w_hat)
			vth = _soft_threshold_l1(v, self.ss * self.p1)

			for p_idx in range(self.P):
				gp = self._w_Gp(p_idx)
				p2_p = _group_penalty_parameter(vth[gp], self.p2)

	def _w_Gp(self, p_idx):
		"""Get set of harmonic coefficients from weights
		p:		pitch index
		"""
		return np.arange(self.H * p_idx, self.H * (p_idx + 1))


def _soft_threshold_l1(arr, alpha):
	"""Soft L1 threshold operator for gradient descent"""
	mval = np.maximum(np.abs(arr) - alpha, 0)
	return mval / (mval + alpha) * arr


def _soft_threshold_l2(arr, alpha):
	"""Soft L2 threshold operator for gradient descent"""
	mval = np.maximum(np.linalg.norm(arr) - alpha, 0)
	return mval / (mval + alpha) * arr


def _group_penalty_parameter(w_hat_p, p2):
	"""Penalty parameter update to discourage erronous sub-octaves
	w_hat_p:		coefficient of the first harmonic of pitch p
	p2:				pre-configured penalty parameter p2
	"""
	# First harmonic is first element of col vector
	denom = np.abs(w_hat_p[0][0]) + 1e-5
	return p2 * max(1, 1 / denom)
