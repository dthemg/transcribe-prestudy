def ct(arr):
	"""Conjugate transpose"""
	return arr.conj().T


def c(arr):
	"""Conjugate"""
	return arr.conj()


def as_column(arr):
	"""Convert array to column vector"""
	return arr.reshape(len(arr), 1)


def as_row(arr):
	"""Convert array to row vector"""
	return arr.reshape(1, len(arr))
