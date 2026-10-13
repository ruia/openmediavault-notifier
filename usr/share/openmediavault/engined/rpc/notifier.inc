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

namespace Engined\Rpc;

class Notifier extends \OMV\Rpc\ServiceAbstract
{
    private const CHANNEL_TYPES = [
        "discord" => "Discord",
        "slack" => "Slack",
        "telegram" => "Telegram",
        "ntfy" => "ntfy",
        "gotify" => "Gotify",
        "email" => "Email",
    ];

    private const REQUIRED_FIELDS = [
        "discord" => ["url"],
        "slack" => ["url"],
        "telegram" => ["token", "chatid"],
        "ntfy" => ["url", "topic"],
        "gotify" => ["url", "token"],
        "email" => [],
    ];

    private const URL_FIELD_TYPES = ["discord", "slack", "ntfy", "gotify"];

    private const CHANNEL_PROPERTIES = [
        "uuid", "enable", "name", "type", "url", "token", "chatid", "topic",
        "recipients", "sendername", "events", "skiprecovery",
    ];

    private const LOCAL_SMTP_HOSTS = ["127.0.0.1", "localhost", "::1"];

    public function getName()
    {
        return "Notifier";
    }

    public function initialize()
    {
        $this->registerMethod("getSettings");
        $this->registerMethod("setSettings");
        $this->registerMethod("getEventClasses");
        $this->registerMethod("getChannelList");
        $this->registerMethod("getChannel");
        $this->registerMethod("setChannel");
        $this->registerMethod("deleteChannel");
        $this->registerMethod("testChannel");
    }

    public function getSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.service.notifier");
        $object->remove("channels");
        return $object->getAssoc();
    }

    public function setSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.notifier.setsettings");
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.service.notifier");
        if ($params['replaceemail'] && $this->hasChannelOfType($db, "email")) {
            $this->assertExternalSmtpServer($db);
        }
        $object->setFlatAssoc([
            "enable" => $params['enable'],
            "replaceemail" => $params['replaceemail'],
            "uiurl" => $params['uiurl'],
        ]);
        $db->set($object);
        $object->remove("channels");
        return $object->getAssoc();
    }

    public function getEventClasses($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        return $this->loadEventClasses();
    }

    public function getChannelList($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.common.getlist");
        $db = \OMV\Config\Database::getInstance();
        $objects = $db->get("conf.service.notifier.channel");
        $objectsAssoc = [];
        foreach ($objects as $object) {
            $object->add("typetext", "string", "");
            $object->set("typetext", self::CHANNEL_TYPES[$object->get("type")]);
            $objectsAssoc[] = $object->getAssoc();
        }
        return $this->applyFilter(
            $objectsAssoc,
            $params['start'],
            $params['limit'],
            $params['sortfield'],
            $params['sortdir']
        );
    }

    public function getChannel($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.notifier.getchannel");
        $db = \OMV\Config\Database::getInstance();
        if ($params['uuid'] === "") {
            $object = new \OMV\Config\ConfigObject("conf.service.notifier.channel");
            $object->set("uuid", \OMV\Environment::get("OMV_CONFIGOBJECT_NEW_UUID"));
        } else {
            $object = $db->get("conf.service.notifier.channel", $params['uuid']);
        }
        $assoc = $this->channelToAssoc($object);
        $assoc['existingnames'] = $this->otherChannelNames($db, $object->get("uuid"));
        return $assoc;
    }

    public function setChannel($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.notifier.setchannel");
        $db = \OMV\Config\Database::getInstance();
        $this->assertChannelParams($params, $db);
        $params['events'] = implode(",", $params['events']);
        $object = new \OMV\Config\ConfigObject("conf.service.notifier.channel");
        $object->setAssoc(array_intersect_key($params, array_flip(self::CHANNEL_PROPERTIES)));
        $db->assertIsUnique($object, "name", sprintf(
            gettext("A channel named '%s' already exists."),
            str_replace("%", "%%", $params['name'])
        ));
        $db->set($object);
        return $this->channelToAssoc($object);
    }

    public function deleteChannel($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.common.objectuuid");
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.service.notifier.channel", $params['uuid']);
        $db->delete($object);
        return $this->channelToAssoc($object);
    }

    public function testChannel($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.common.objectuuid");
        if ($this->isModuleDirty("notifier")) {
            throw new \OMV\Config\ConfigDirtyException();
        }
        $cmd = new \OMV\System\Process("omv-notifier", [
            "test", escapeshellarg($params['uuid'])
        ]);
        $cmd->setRedirect2to1();
        $cmd->execute($output);
        return implode("\n", $output);
    }

    private function channelToAssoc(\OMV\Config\ConfigObject $object)
    {
        $assoc = $object->getAssoc();
        $assoc['events'] = array_values(array_filter(
            explode(",", $assoc['events']),
            fn($event) => $event !== ""
        ));
        return $assoc;
    }

    private function assertChannelParams(array $params, \OMV\Config\Database $db)
    {
        $type = $params['type'];
        foreach (self::REQUIRED_FIELDS[$type] as $field) {
            if (trim($params[$field]) === "") {
                throw new \OMV\Exception(
                    "The field '%s' is required for channel type '%s'.",
                    $field,
                    self::CHANNEL_TYPES[$type]
                );
            }
        }
        if (in_array($type, self::URL_FIELD_TYPES, true)) {
            $url = trim($params['url']);
            if (filter_var($url, FILTER_VALIDATE_URL) === false ||
                    preg_match('#^https?://#i', $url) !== 1) {
                throw new \OMV\Exception(
                    "The URL '%s' is invalid, it must start with http:// or https://.",
                    $url
                );
            }
        }
        if ($type === "email") {
            foreach ($this->splitList($params['recipients']) as $recipient) {
                if (filter_var($recipient, FILTER_VALIDATE_EMAIL) === false) {
                    throw new \OMV\Exception(
                        "The recipient '%s' is not a valid email address.",
                        $recipient
                    );
                }
            }
            $settings = $db->get("conf.service.notifier");
            if ($settings->get("replaceemail")) {
                $this->assertExternalSmtpServer($db);
            }
        }
        $known = array_column($this->loadEventClasses(), "value");
        foreach ($params['events'] as $event) {
            if (!in_array($event, $known, true)) {
                throw new \OMV\Exception("Unknown event class '%s'.", $event);
            }
        }
    }

    private function otherChannelNames(\OMV\Config\Database $db, string $uuid): array
    {
        $names = [];
        foreach ($db->get("conf.service.notifier.channel") as $object) {
            if ($object->get("uuid") !== $uuid) {
                $names[] = $object->get("name");
            }
        }
        return $names;
    }

    private function hasChannelOfType(\OMV\Config\Database $db, string $type): bool
    {
        return $db->exists("conf.service.notifier.channel", [
            "operator" => "stringEquals",
            "arg0" => "type",
            "arg1" => $type
        ]);
    }

    private function assertExternalSmtpServer(\OMV\Config\Database $db)
    {
        $email = $db->get("conf.system.notification.email");
        $server = strtolower(trim($email->get("server")));
        if (in_array($server, self::LOCAL_SMTP_HOSTS, true)) {
            throw new \OMV\Exception(
                "Replacing openmediavault emails together with an email channel " .
                "requires an external SMTP server in the notification settings, " .
                "otherwise the improved emails would be discarded as well."
            );
        }
    }

    private function loadEventClasses(): array
    {
        $cmd = new \OMV\System\Process("omv-notifier", ["events"]);
        $cmd->setRedirect2to1();
        $cmd->execute($output);
        $classes = json_decode_safe(implode("", $output), true);
        if (!is_array($classes)) {
            throw new \OMV\Exception(
                "Failed to parse the output of 'omv-notifier events': %s",
                json_last_error_msg()
            );
        }
        return $classes;
    }

    private function splitList(string $value): array
    {
        return array_values(array_filter(
            array_map("trim", explode(",", $value)),
            fn($item) => $item !== ""
        ));
    }
}
