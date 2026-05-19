pkgname=probe
pkgver=1.0.0
pkgrel=1
pkgdesc="Probe"

arch=('x86_64' 'aarch64')

license=('MIT')

depends=(
    'python'
    'python-requests'
    'python-yaml'
    'libnl'
)

source=(
    "pi_agent.py"
    "configs/"
    "probe.service"
)

package() {

    install -Dm755 pi_agent.py \
        "$pkgdir/opt/probe/pi_agent.py"


    install -Dm644 probe.service \
        "$pkgdir/usr/lib/systemd/system/probe.service"

    install -Dm644 configs/config.yaml \
        "$pkgdir/etc/probe/config.yaml"

    install -d "$pkgdir/opt/probe/plugins"
}