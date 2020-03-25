#!/usr/bin/env bash
set -e

if [[ -z "${PIP_INSTALL}" ]]; then
    PIP_INSTALL='install'
fi

# Directory of *this* script
this_dir="$( cd "$( dirname "$0" )" && pwd )"
src_dir="$(realpath "${this_dir}/..")"

python_name="$(basename "${src_dir}" | sed -e 's/-//' | sed -e 's/-/_/g')"

# -----------------------------------------------------------------------------

architecture="$1"
if [[ -z "${architecture}" ]]; then
    architecture="$(bash "${src_dir}/architecture.sh")"
fi

venv="${src_dir}/.venv"
download="${src_dir}/download"

# -----------------------------------------------------------------------------

# Create virtual environment
echo "Creating virtual environment at ${venv}"
rm -rf "${venv}"
python3 -m venv "${venv}"
source "${venv}/bin/activate"

# Install Python dependencies
echo "Installing Python dependencies"
pip3 ${PIP_INSTALL} --upgrade pip
pip3 ${PIP_INSTALL} --upgrade wheel setuptools

# Install pocketsphinx (no PulseAudio)
pocketsphinx_file="${download}/pocketsphinx-python.tar.gz"
if [[ ! -s "${pocketsphinx_file}" ]]; then
    wget -O "${pocketsphinx_file}" 'https://github.com/synesthesiam/pocketsphinx-python/releases/download/v1.0/pocketsphinx-python.tar.gz'
fi

pip3 ${PIP_INSTALL} "${pocketsphinx_file}"

# Install local Rhasspy dependencies if available
grep '^rhasspy-' "${src_dir}/requirements.txt" | \
    xargs pip3 ${PIP_INSTALL} -f "${download}"

pip3 ${PIP_INSTALL} -r requirements.txt

# Optional development requirements
pip3 ${PIP_INSTALL} -r requirements_dev.txt || \
    echo "Failed to install development requirements"

# -----------------------------------------------------------------------------

# Check for opengrm
if [[ -n "$(command -v ngramcount)" ]]; then
    echo 'Missing libngram-tools'
    echo 'Run: apt-get install libngram-tools'
fi

# Install MITLM
# echo 'Installing MITLM'
# "${src_dir}/scripts/install-mitlm.sh" \
#     "${download}/mitlm-0.4.2-${architecture}.tar.gz" \
#     "${src_dir}/${python_name}"

# Install Phonetisaurus
echo 'Installing Phonetisaurus'
"${src_dir}/scripts/install-phonetisaurus.sh" \
    "${download}/phonetisaurus-2019-${architecture}.tar.gz" \
    "${src_dir}/${python_name}"

# -----------------------------------------------------------------------------

echo "OK"
