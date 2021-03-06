import numpy as np
from tqdm import tqdm

import matplotlib.pyplot as plt

from utils import c, ct, as_col, as_row, r

# https://dl.acm.org/doi/pdf/10.1109/TASLP.2016.2634118
# http://www.maths.lu.se/fileadmin/maths/personal_staff/Andreas_Jakobsson/openPEARLS.pdf
# http://lup.lub.lu.se/search/ws/files/26854757/thesis_FilipElvander.pdf
# file:///C:/Users/david/Downloads/Multi-Pitch_Estimation.pdf


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
		mu: float,
	):
		"""
		signal:     input signal (1 channel)
		lambda_:    forgetting factor
		xi:         smoothing factor
		H:          maximum number of harmonics
		fs:         sampling frequency
		K_msecs:    number of milliseconds to produce a pitch
		p1:         penalty factor 1
		p2:         penalty factor 2
		ss:         step size for gradient descent
		mgi:        max gradient iterations for gradient descent
		mu: 		penalty update parameter
		"""
		self.s = signal
		self.complex_dtype = "complex_"
		self.float_dtype = "float"
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
		self.mu = mu

		self.norm_thresh = 0.01

	def initialize_variables(self, f_int: tuple, f_spacing: float) -> None:
		"""
		f_int:      (min, max) frequency search interval
		f_spacing:  initial spacing between frequencies
		"""
		# Initialize frequency matrix as [harmonic, pitch]
		ps = np.arange(f_int[0], f_int[1] + 0.001, f_spacing, dtype=self.float_dtype)
		ps = np.array([100, 278.2, 300, 400, 500])
		self.P = len(ps)
		self.f_mat = np.arange(1, self.H + 1) * as_col(ps)
		self.f_active = [True] * self.P

		# Initialize penalty update parameters
		self.Delta = _get_window_length(self.lambda_)
		self.Lambda_ = np.diag(np.power(self.lambda_, np.arange(self.Delta)[::-1]))

		# Initialize time variables
		self.t = np.arange(self.L + self.K) / self.fs
		self.t_stop = self.K
		self.tvec = self.t[: self.t_stop]

		# Initialize pitch-time matrix and vector
		self._update_a(fs_updated=True)

		# Initialize covariance matrix/vector
		self.R = self.a @ ct(self.a)
		self.r = self.s[0] * np.conj(self.a)

		# Initialize RLS filter coefficients
		n_coef = self.P * self.H
		self.rls = np.zeros((n_coef, 1), dtype=self.complex_dtype)

		# Initialize RLS smoothing matrix
		self.I_xi = self.xi * np.eye(self.H)

		# Initialize weights
		self.w_hat = np.zeros((n_coef, 1), dtype=self.complex_dtype)

		# Active pitch indicies
		self.act = np.arange(self.P)

		# Initialize result history
		self.rls_hist = np.zeros((n_coef, self.L), dtype=self.complex_dtype)
		self.w_hat_hist = np.zeros((n_coef, self.L), dtype=self.complex_dtype)
		self.freq_hist = np.zeros((self.P, self.L), dtype=self.float_dtype)
		self.p1_hist = np.zeros(self.L, dtype=self.float_dtype)
		self.p2_hist = np.zeros(self.L, dtype=self.float_dtype)

	def _increment_time_vars(self) -> None:
		"""Increment time variables"""
		self.t_stop += 1
		self.tvec = self.t[self.t_stop - self.K : self.t_stop]

	def _update_a(self, fs_updated: bool) -> None:
		"""Update a vector and A matrix
		f_updated:  If updates has been done to the frequency matrix
		"""
		if fs_updated:
			self.A = np.exp(as_col(self.tvec) * 2 * np.pi * 1j * r(self.f_mat))
			self.a = as_col(self.A[-1, :])
		else:
			tval = self.t[self.t_stop - 1]
			self.a = np.exp(as_col(2 * np.pi * 1j * r(self.f_mat)) * tval)
			self.A = np.roll(self.A, -1, axis=0)
			self.A[-1, :] = r(self.a)

	def _update_r(self, s_val: float) -> None:
		"""Update r vector and R matrix
		s_val:      signal value
		"""
		self.R = self.lambda_ * self.R + self.a @ ct(self.a)
		self.r = self.lambda_ * self.r + s_val * c(self.a)

	def _penalty_parameter_update(self, stop_idx: int) -> None:
		A_win = self.A[-self.Delta :, :]
		s_win = as_col(self.s[stop_idx - self.Delta : stop_idx])
		s_win = np.pad(s_win, (max(0, self.Delta - len(s_win)), 0), "constant")
		eta = self.mu * np.linalg.norm(ct(self.Lambda_ @ A_win) @ s_win, ord=np.inf)

		self.p1 = 0.1 * eta
		self.p2 = 1.0 * eta

	def run_algorithm(self) -> dict:
		"""Run PEARLS algorithm through signal"""

		# If frequency matrix has been updated
		fs_upd = False
		for idx in range(self.L):
			if idx % 100 == 0:
				print(f"Sample {idx}/{self.L}")
			self._penalty_parameter_update(idx + 1)
			sval = self.s[idx]

			self._increment_time_vars()
			self._update_a(fs_upd)
			self._update_r(sval)
			self._gradient_descent()
			self._find_active_set()
			if idx > 50:
				self._rls_update()
			if idx % 100 == 0:
				self.dictionary_update()
			self._save_history(idx)

		results = {
			"w_hat_hist": self.w_hat_hist,
			"freq_hist": self.freq_hist,
			"p1_hist": self.p1_hist,
			"p2_hist": self.p2_hist,
			"rls_hist": self.rls_hist,
		}
		return results

	def _find_active_set(self) -> None:
		"""Update the set of active pitches"""
		w_hat_mat = self.w_hat.reshape((self.P, self.H))
		norms = np.linalg.norm(w_hat_mat, axis=1)
		max_norm = max(norms)
		for p in np.argwhere(norms < self.norm_thresh * max_norm):
			gp = self._Gp(p)
			self.w_hat[gp] = as_col(np.zeros_like(gp))
		self.act = np.argwhere(norms > self.norm_thresh)

	def _save_history(self, idx) -> None:
		"""Save results
		idx: 	Signal sample iteration index
		"""
		self.w_hat_hist[:, idx] = r(self.w_hat)
		self.freq_hist[:, idx] = r(self.f_mat[:, 0])
		self.rls_hist[:, idx] = r(self.rls)
		self.p1_hist[idx] = self.p1
		self.p2_hist[idx] = self.p2

	def _rls_update(self) -> None:
		"""Refine amplitude estimates of active pitches"""
		S = []
		for p in self.act:
			S.extend(self._Gp(p[0]))  # 0 since column
		t_rls = np.copy(self.rls)

		for p in self.act:
			gp = self._Gp(p)
			qp = np.setdiff1d(S, gp)

			rp = self.r[gp] - self.R[np.ix_(gp, qp)] @ t_rls[qp]

			inv_part = np.linalg.inv(self.R[np.ix_(gp, gp)] + self.I_xi)
			col_part = rp + self.xi * t_rls[gp]

			self.rls[gp] = inv_part @ col_part

		for p in range(self.P):
			if p not in self.act:
				gp = self._Gp(p)
				self.rls[gp] = as_col(np.zeros_like(gp))

	def _gradient_descent(self) -> None:
		"""Perform gradient descent on parameter weights"""
		for _ in range(self.mgi):
			v = self.w_hat + self.ss * (self.r - self.R @ self.w_hat)
			vth = _S1(v, self.ss * self.p1)

			for p_idx in range(self.P):
				gp = self._Gp(p_idx)
				p2_p = _group_penalty_parameter(vth[gp], self.p2)
				self.w_hat[gp] = _S2(vth[gp], self.ss * p2_p)

	def _Gp(self, p_idx: int) -> None:
		"""Get set of harmonic coefficients from weights
		p:		pitch index
		"""
		return np.arange(self.H * p_idx, self.H * (p_idx + 1))

	def dictionary_update(self):
		"""Refine frequency estimates"""
		rls_mat = self.rls.reshape((self.P, self.H))
		norms = np.linalg.norm(rls_mat, axis=1)
		max_norm = max(norms)
		sig_pitches = r(np.argwhere(norms > max_norm * 0.05))

		for p in sig_pitches:
			gp = self._Gp(p)

			# Estimate num harmonics
			p_rls = rls_mat[p, :]
			H = np.max(np.argwhere(abs(p_rls) > np.max(abs(p_rls)) * 0.2))

			# breakpoint()

			# freq = self.freq_mat[p, 0]


def _S1(arr: np.ndarray, alpha: float) -> np.ndarray:
	"""Soft L1 threshold operator for gradient descent"""
	mval = np.maximum(np.abs(arr) - alpha, 0)
	return mval / (mval + alpha + 1e-10) * arr


def _S2(arr: np.ndarray, alpha: float) -> np.ndarray:
	"""Soft L2 threshold operator for gradient descent"""
	mval = np.maximum(np.linalg.norm(arr) - alpha, 0)
	return mval / (mval + alpha + 1e-10) * arr


def _group_penalty_parameter(w_hat_p: np.ndarray, p2: float) -> float:
	"""Penalty parameter update to discourage erronous sub-octaves
	w_hat_p:		coefficient of the first harmonic of pitch p
	p2:				penalty parameter p2
	"""
	# First harmonic is first element of col vector
	denom = np.abs(w_hat_p[0][0]) + 1e-5
	return p2 * max(1, min(1000, 1 / denom))


def _get_window_length(lambda_: float) -> int:
	"""Get penalty window length
	lambda_:	forgetting factor
	"""
	return int(np.log(0.01) / np.log(lambda_))
