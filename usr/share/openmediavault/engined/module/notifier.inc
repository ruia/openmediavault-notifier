<?php

/**
 * This file is part of openmediavault-notifier.
 *
 * @license   https://www.gnu.org/licenses/gpl.html GPL Version 3
 * @copyright Copyright (c) 2026 Rui Almeida
 *
 * openmediavault-notifier is free software: you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as published
 * by the Free Software Foundation, either version 3 of the License, or
 * any later version.
 *
 * openmediavault-notifier is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

namespace Engined\Module;

class Notifier extends \OMV\Engine\Module\ServiceAbstract implements \OMV\Engine\Notify\IListener
{
    public function getName()
    {
        return "notifier";
    }

    public function getDescription()
    {
        return gettext("Forwards system notifications to chat services and email.");
    }

    public function deployAfter(): array
    {
        return ["email"];
    }

    public function bindListeners(\OMV\Engine\Notify\Dispatcher $dispatcher)
    {
        $dispatcher->addListener(
            OMV_NOTIFY_MODIFY,
            "org.openmediavault.conf.service.notifier",
            [$this, "setDirty"]
        );
        $dispatcher->addListener(
            OMV_NOTIFY_CREATE | OMV_NOTIFY_MODIFY | OMV_NOTIFY_DELETE,
            "org.openmediavault.conf.service.notifier.channel",
            [$this, "setDirty"]
        );
        $dispatcher->addListener(
            OMV_NOTIFY_MODIFY,
            "org.openmediavault.conf.system.notification.email",
            [$this, "setDirty"]
        );
        $dispatcher->addListener(
            OMV_NOTIFY_MODIFY,
            "org.openmediavault.conf.system.network.dns",
            [$this, "setDirty"]
        );
        $dispatcher->addListener(
            OMV_NOTIFY_CREATE | OMV_NOTIFY_MODIFY | OMV_NOTIFY_DELETE,
            "org.openmediavault.conf.system.filesystem.mountpoint",
            [$this, "setDirty"]
        );
        $dispatcher->addListener(
            OMV_NOTIFY_CREATE | OMV_NOTIFY_MODIFY | OMV_NOTIFY_DELETE,
            "org.openmediavault.conf.system.sharedfolder",
            [$this, "setDirty"]
        );
    }
}
