pkgname=probe
pkgver=v1.0.0.0.g1d056fa
pkgrel=1
pkgdesc="Probe"
arch=('x86_64' 'aarch64')
license=('MIT')

depends=(
  python
  python-requests
  python-pyyaml

  libnl

  iproute2
  
  wpa_supplicant
  wireless_tools
  procps-ng
  sudo
  systemd
)

makedepends=(
  git
  gcc
  make
  linux-headers
)

source=("git+https://github.com/vhfba/probe.git")
sha256sums=('SKIP')

pkgver() {
  cd "$srcdir/probe"
  git describe --tags --long | sed 's/-/./g'
}

package() {
  cd "$srcdir/probe"

  install -d "$pkgdir/opt/probe"
  install -d "$pkgdir/opt/probe/configs"
  install -d "$pkgdir/opt/probe/plugins"

  install -Dm755 pi_agent.py "$pkgdir/opt/probe/pi_agent.py"

  install -Dm644 configs/config.yaml \
    "$pkgdir/opt/probe/configs/config.yaml"

  install -Dm644 probe.service \
    "$pkgdir/usr/lib/systemd/system/probe.service"
}